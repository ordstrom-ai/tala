import json
import logging
from io import StringIO
from unittest.mock import Mock

import pytest
import structlog

from tala.utils import func


class TestFuncBaseLogContext:
    @pytest.mark.parametrize("request_id_source", ["top", "request", "session"])
    def test_logger_context_includes_request_offer_and_turn(self, request_id_source):
        self.given_request_context(request_id_source)
        self.when_request_logger_is_initialized()
        self.then_the_identifiers_are_bound_to_the_logger()

    def test_missing_optional_context_does_not_create_fake_identifiers(self):
        self.given_a_request_without_context()
        self.when_request_logger_is_initialized()
        self.then_only_the_existing_missing_context_markers_are_bound()

    def test_top_level_request_id_takes_precedence(self):
        self.given_request_context("top")
        self.request["request"] = {"request_id": "nested-request"}
        self.request["session"]["request_id"] = "session-request"
        self.when_request_logger_is_initialized()
        self.then_the_identifiers_are_bound_to_the_logger()

    def given_request_context(self, request_id_source):
        self.logger = Mock()
        self.request = {
            "session": {
                "session_id": "session-456",
                "device_id": "device-789",
                "offer_id": "offer-abc",
                "turn_counter": 0,
            }
        }
        if request_id_source == "top":
            self.request["request_id"] = "request-123"
        elif request_id_source == "request":
            self.request["request"] = {"request_id": "request-123"}
        else:
            self.request["session"]["request_id"] = "request-123"

    def given_a_request_without_context(self):
        self.logger = Mock()
        self.request = {}

    def when_request_logger_is_initialized(self):
        self.function = func.FuncBase()
        self.function._setup_logger(self.request, self.logger)

    def then_the_identifiers_are_bound_to_the_logger(self):
        self.logger.bind.assert_called_once_with(
            session_id="session-456",
            device_id="device-789",
            request_id="request-123",
            correlation_id="request-123",
            offer_id="offer-abc",
            turn_id=0,
        )
        assert self.function.logger is self.logger.bind.return_value

    def then_only_the_existing_missing_context_markers_are_bound(self):
        self.logger.bind.assert_called_once_with(session_id="unknown-session-id", device_id="unknown-device-id")


class TestBoundedJSONRenderer:
    def setup_method(self):
        self.renderer = func.BoundedJSONRenderer()

    @pytest.mark.parametrize("field", ["body", "request", "request_data", "response", "exception"])
    def test_oversized_payload_fields_are_stored_and_referenced(self, field):
        self.given_an_archive_writer()
        self.given_an_event_with_an_oversized_field(field)
        self.when_the_event_is_rendered_with_archive_writer()
        self.then_the_complete_event_is_retrievable_from_the_archive()

    def test_oversized_event_is_stored_and_summary_contains_its_retrieval_id(self):
        self.given_an_archive_writer()
        self.given_an_event_with_an_oversized_field("body")
        self.when_the_event_is_rendered_with_archive_writer()
        self.then_the_full_event_can_be_retrieved_from_the_archive()

    def test_archive_writer_can_be_configured_after_renderer_initialization(self):
        self.given_an_event_with_an_oversized_field("body")
        self.archive = RecordingSnapshotWriter()
        previous_archive = func.set_log_snapshot_writer(self.archive)
        previous_policy = func.set_log_snapshot_policy(SyntheticDiagnosticPolicy())
        try:
            self.when_the_event_is_rendered_with_archive_writer()
            self.then_the_full_event_can_be_retrieved_from_the_archive()
        finally:
            func.set_log_snapshot_writer(previous_archive)
            func.set_log_snapshot_policy(previous_policy)

    def test_multiple_large_fields_leave_identifiers_and_a_valid_record(self):
        self.given_an_archive_writer()
        self.given_an_event_with_multiple_oversized_fields()
        self.when_the_event_is_rendered_with_archive_writer()
        self.then_all_large_fields_are_in_the_same_retrievable_event()

    def test_only_bulky_fields_are_replaced_after_a_successful_snapshot(self):
        self.given_an_archive_writer()
        self.given_an_event_with_an_oversized_field("body")
        self.event_dict.update(endpoint="ndu", duration_ms=12, status_detail="short synthetic diagnostic")
        self.when_the_event_is_rendered()
        self.then_small_fields_are_kept_and_the_large_body_is_referenced()

    def test_record_budget_must_allow_snapshot_metadata(self):
        with pytest.raises(ValueError, match="256"):
            func.BoundedJSONRenderer(max_bytes=128)

    def test_small_records_are_not_modified(self):
        self.given_a_small_event()
        self.when_the_event_is_rendered()
        self.then_the_event_is_valid_json_with_prioritized_metadata()

    def test_strict_renderer_reports_archive_unavailable_without_throwing(self):
        self.given_no_archive_writer()
        self.given_an_event_with_an_oversized_field("body")
        self.when_the_event_is_rendered_with_archive_writer()
        self.then_archive_unavailability_is_visible_and_the_log_is_bounded()

    def test_strict_renderer_reports_archive_failure_without_throwing(self):
        self.given_an_archive_writer_that_fails()
        self.given_an_event_with_an_oversized_field("body")
        self.when_the_event_is_rendered_with_archive_writer()
        self.then_archive_failure_is_visible_and_the_log_is_bounded()

    def test_archive_failure_does_not_leak_exception_text(self):
        self.given_an_archive_writer_that_fails_with_sensitive_message()
        self.given_an_event_with_an_oversized_field("body")
        self.when_the_event_is_rendered_with_archive_writer()
        self.then_archive_failure_does_not_include_exception_text()

    def given_an_event_with_an_oversized_field(self, field):
        self.original_payload = {"text": "å" * 10_000}
        self.event_dict = {
            "body": "body metadata",
            "event": "sending downstream request",
            "level": "info",
            "logger": "test_service",
            "request_id": "request-123",
            "session_id": "session-456",
        }
        self.event_dict[field] = self.original_payload

    def given_an_event_with_multiple_oversized_fields(self):
        self.event_dict = {
            "event": "service call",
            "level": "warning",
            "request_id": "request-123",
            "body": {
                "text": "x" * 20_000
            },
            "response": {
                "text": "y" * 20_000
            },
            "request_data": "z" * 20_000,
        }

    def given_a_small_event(self):
        self.event_dict = {"session_id": "session-456", "event": "request accepted", "level": "info"}

    def given_an_archive_writer(self):
        self.archive = RecordingSnapshotWriter()
        self.renderer = func.BoundedJSONRenderer(
            snapshot_writer=self.archive, snapshot_policy=SyntheticDiagnosticPolicy()
        )

    def given_no_archive_writer(self):
        self.renderer = func.BoundedJSONRenderer(preserve_unarchived_fields=False)

    def given_an_archive_writer_that_fails(self):
        self.archive = FailingSnapshotWriter()
        self.renderer = func.BoundedJSONRenderer(
            snapshot_writer=self.archive, snapshot_policy=SyntheticDiagnosticPolicy(), preserve_unarchived_fields=False
        )

    def given_an_archive_writer_that_fails_with_sensitive_message(self):
        self.archive = FailingSnapshotWriter(error_message="do-not-log-this-secret")
        self.renderer = func.BoundedJSONRenderer(
            snapshot_writer=self.archive, snapshot_policy=SyntheticDiagnosticPolicy(), preserve_unarchived_fields=False
        )

    def when_the_event_is_rendered(self):
        self.rendered = self.renderer(None, None, self.event_dict)
        self.parsed = json.loads(self.rendered)

    def when_the_event_is_rendered_with_archive_writer(self):
        self.when_the_event_is_rendered()

    def then_the_record_is_bounded_and_metadata_is_preserved(self, field):
        self.then_the_complete_event_is_retrievable_from_the_archive()

    def then_the_complete_event_is_retrievable_from_the_archive(self):
        assert len(self.rendered.encode("utf-8")) <= func.MAX_LOG_RECORD_BYTES
        assert self.parsed["event"] == "sending downstream request"
        assert self.parsed["request_id"] == "request-123"
        assert self.parsed["log_snapshot_state"] == "stored"
        snapshot_id = self.parsed["log_snapshot_id"]
        assert self.archive.records[snapshot_id] == self.event_dict
        assert len(self.archive.serialized[snapshot_id].encode("utf-8")) > func.MAX_LOG_RECORD_BYTES
        assert self.parsed["log_fields_archived"] > 0
        assert self.original_payload["text"] == "å" * 10_000

    def then_all_large_fields_are_in_the_same_retrievable_event(self):
        assert len(self.rendered.encode("utf-8")) <= func.MAX_LOG_RECORD_BYTES
        assert self.parsed["event"] == "service call"
        assert self.parsed["request_id"] == "request-123"
        assert self.parsed["log_snapshot_state"] == "stored"
        archived_event = self.archive.records[self.parsed["log_snapshot_id"]]
        assert archived_event["body"]["text"] == "x" * 20_000
        assert archived_event["response"]["text"] == "y" * 20_000
        assert archived_event["request_data"] == "z" * 20_000

    def then_small_fields_are_kept_and_the_large_body_is_referenced(self):
        assert self.parsed["endpoint"] == "ndu"
        assert self.parsed["duration_ms"] == 12
        assert self.parsed["status_detail"] == "short synthetic diagnostic"
        assert self.parsed["body"]["in_snapshot"] is True
        assert self.parsed["log_fields_archived"] == 1
        assert self.archive.records[self.parsed["log_snapshot_id"]] == self.event_dict
        assert len(self.rendered.encode("utf-8")) <= func.MAX_LOG_RECORD_BYTES

    def then_the_event_is_valid_json_with_prioritized_metadata(self):
        assert self.parsed == {"event": "request accepted", "level": "info", "session_id": "session-456"}

    def then_the_full_event_can_be_retrieved_from_the_archive(self):
        assert self.parsed["log_snapshot_state"] == "stored"
        snapshot_id = self.parsed["log_snapshot_id"]
        assert self.archive.records[snapshot_id] == self.event_dict
        assert self.parsed["request_id"] == "request-123"
        assert self.parsed["log_fields_archived"] > 0

    def then_archive_unavailability_is_visible_and_the_log_is_bounded(self):
        assert self.parsed["log_snapshot_state"] == "not_configured"
        assert "log_snapshot_id" in self.parsed
        assert len(self.rendered.encode("utf-8")) <= func.MAX_LOG_RECORD_BYTES

    def then_archive_failure_is_visible_and_the_log_is_bounded(self):
        assert self.parsed["log_snapshot_state"] == "failed"
        assert self.parsed["log_snapshot_error"] == "RuntimeError"
        assert "log_snapshot_id" in self.parsed
        assert len(self.rendered.encode("utf-8")) <= func.MAX_LOG_RECORD_BYTES

    def then_archive_failure_does_not_include_exception_text(self):
        assert self.parsed["log_snapshot_state"] == "failed"
        assert "do-not-log-this-secret" not in self.rendered


class RecordingSnapshotWriter:
    def __init__(self):
        self.records = {}
        self.serialized = {}

    def write_snapshot(self, snapshot_id, snapshot_json):
        self.serialized[snapshot_id] = snapshot_json
        self.records[snapshot_id] = json.loads(snapshot_json)


class SyntheticDiagnosticPolicy:
    """Only test fixtures use this permissive policy; never application capture."""
    def permits_snapshot(self, event):
        return True


class TestSnapshotAdmission:
    def test_a_writer_alone_does_not_authorize_capture(self, monkeypatch):
        monkeypatch.setattr(func, "_LOG_SNAPSHOT_POLICY", None, raising=False)
        self.given_a_safe_oversized_event()
        self.archive = RecordingSnapshotWriter()
        self.renderer = func.BoundedJSONRenderer(snapshot_writer=self.archive)
        self.when_the_event_is_rendered()
        self.then_the_original_is_preserved_without_a_snapshot("capture_policy_not_configured")

    @pytest.mark.parametrize("decision", [False, None, 1, "true"])
    def test_policy_must_explicitly_approve_the_event(self, decision):
        self.given_a_safe_oversized_event()
        self.given_an_admission_policy()
        self.policy.permits_snapshot.return_value = decision
        self.when_the_event_is_rendered()
        self.then_the_original_is_preserved_without_a_snapshot("capture_policy_rejected")

    def test_policy_failure_keeps_processing_without_exposing_its_error_text(self):
        self.given_a_safe_oversized_event()
        self.given_an_admission_policy()
        self.policy.permits_snapshot.side_effect = RuntimeError("do-not-log-this-secret")
        self.when_the_event_is_rendered()
        self.then_the_original_is_preserved_without_a_snapshot("capture_policy_failed")
        assert self.parsed["log_snapshot_error"] == "RuntimeError"
        assert "do-not-log-this-secret" not in self.rendered

    @pytest.mark.parametrize("strict", [True, False])
    @pytest.mark.parametrize(
        "payload", [
            {
                "utterance": "synthetic private input"
            },
            {
                "request": {
                    "hypotheses": [{
                        "utterance": "synthetic private input"
                    }]
                }
            },
            {
                "body": {
                    "messages": [{
                        "role": "user",
                        "content": "synthetic private input"
                    }]
                }
            },
            {
                "response": {
                    "full_reply_content": "synthetic private output"
                }
            },
            {
                "message": {
                    "event": "STREAMING_CHUNK",
                    "data": "synthetic private output"
                }
            },
            {
                "events": [{
                    "event_type": "user_utterance_received",
                    "text": "synthetic private input"
                }]
            },
            {
                "events": [{
                    "event_type": "utterance_corrected",
                    "text": "synthetic private correction"
                }]
            },
            {
                "events": [{
                    "event_type": "system_utterance_fragment",
                    "text": "synthetic private output"
                }]
            },
        ]
    )
    def test_transcript_content_is_neither_archived_nor_removed_by_generic_snapshotting(self, payload, strict):
        self.given_a_safe_oversized_event()
        self.event.update(payload)
        self.event["diagnostic_detail"] = "x" * 10_000
        self.given_an_admission_policy(strict=strict)
        self.when_the_event_is_rendered()
        self.then_the_original_is_preserved_without_a_snapshot("transcript_content_not_permitted")
        self.policy.permits_snapshot.assert_not_called()

    def test_admission_cannot_mutate_the_original_or_stored_event(self):
        self.given_a_safe_oversized_event()
        self.given_an_admission_policy()

        def permit_copy(event):
            event["body"]["diagnostic"] = "mutated policy input"
            return True

        self.policy.permits_snapshot.side_effect = permit_copy
        self.when_the_event_is_rendered()
        assert self.parsed["log_snapshot_state"] == "stored"
        assert self.archive.records[self.parsed["log_snapshot_id"]] == self.event
        assert self.event["body"]["diagnostic"] == "x" * 10_000

    def test_small_transcript_logs_are_unchanged_and_never_snapshotted(self):
        self.given_an_admission_policy()
        self.event = {"event": "utterance received", "utterance": "synthetic input"}
        self.when_the_event_is_rendered()
        assert self.parsed == self.event
        assert self.archive.records == {}
        self.policy.permits_snapshot.assert_not_called()

    def given_a_safe_oversized_event(self):
        self.event = {"event": "synthetic diagnostic", "body": {"diagnostic": "x" * 10_000}}

    def given_an_admission_policy(self, strict=False):
        self.archive = RecordingSnapshotWriter()
        self.policy = Mock(spec=["permits_snapshot"])
        self.policy.permits_snapshot.return_value = True
        self.renderer = func.BoundedJSONRenderer(
            snapshot_writer=self.archive, snapshot_policy=self.policy, preserve_unarchived_fields=not strict
        )

    def when_the_event_is_rendered(self):
        self.rendered = self.renderer(None, None, self.event)
        self.parsed = json.loads(self.rendered)

    def then_the_original_is_preserved_without_a_snapshot(self, reason):
        assert {field: self.parsed[field] for field in self.event} == self.event
        assert self.parsed["log_snapshot_state"] == "not_permitted"
        assert self.parsed["log_snapshot_reason"] == reason
        assert self.archive.records == {}


class FailingSnapshotWriter:
    def __init__(self, error_message="storage is offline"):
        self.error_message = error_message

    def write_snapshot(self, snapshot_id, snapshot_json):
        raise RuntimeError(self.error_message)


class TestConfigureStdoutLogging:
    def test_removing_policy_disables_snapshots_for_an_existing_logger(self, monkeypatch):
        self.given_a_capturing_root_handler(monkeypatch)
        self.given_an_archive_writer()
        func.configure_stdout_logging("INFO")
        logger = structlog.get_logger("test_service")
        logger.info("approved event", body={"diagnostic": "x" * 10_000})
        func.set_log_snapshot_policy(None)
        logger.info("unapproved event", body={"diagnostic": "y" * 10_000})
        first, second = map(json.loads, self.stream.getvalue().splitlines())
        assert first["log_snapshot_state"] == "stored"
        assert second["log_snapshot_state"] == "not_permitted"
        assert second["body"] == {"diagnostic": "y" * 10_000}
        assert len(self.archive.records) == 1

    def test_transcript_guard_runs_through_the_standard_logger(self, monkeypatch):
        self.given_a_capturing_root_handler(monkeypatch)
        self.given_an_archive_writer()
        func.configure_stdout_logging("INFO")
        raw_text = "synthetic private input " * 1_000
        structlog.get_logger("test_service").info("utterance received", utterance=raw_text)
        record = json.loads(self.stream.getvalue().strip())
        assert record["utterance"] == raw_text
        assert record["log_snapshot_state"] == "not_permitted"
        assert record["log_snapshot_reason"] == "transcript_content_not_permitted"
        assert self.archive.records == {}

    def test_configure_preserves_existing_root_handler_and_does_not_duplicate_it(self, monkeypatch):
        self.given_an_existing_root_handler(monkeypatch)
        self.when_logging_is_configured_twice()
        self.then_the_existing_handler_is_preserved_once()

    def test_configure_does_not_close_existing_root_handlers(self, monkeypatch):
        self.given_an_existing_root_handler(monkeypatch)
        self.handler.close = Mock(wraps=self.handler.close)
        self.when_logging_is_configured_twice()
        self.handler.close.assert_not_called()

    def test_configured_logger_emits_bounded_json_through_the_preserved_handler(self, monkeypatch):
        self.given_a_capturing_root_handler(monkeypatch)
        self.given_an_archive_writer()
        self.when_logging_a_request_with_a_large_body()
        self.then_the_captured_record_is_bounded_json_with_request_context()

    def test_configured_logger_preserves_large_fields_when_archive_is_not_configured(self, monkeypatch):
        self.given_a_capturing_root_handler(monkeypatch)
        self.given_no_archive_writer()
        self.when_logging_a_request_with_a_large_body()
        self.then_the_large_body_is_preserved_with_unavailable_archive_status()

    def test_configured_logger_preserves_large_fields_when_archive_write_fails(self, monkeypatch):
        self.given_a_capturing_root_handler(monkeypatch)
        self.given_a_failing_archive_writer()
        self.when_logging_a_request_with_a_large_body()
        self.then_the_large_body_is_preserved_with_failed_archive_status()

    def test_removing_the_archive_writer_restores_fallback_for_an_existing_logger(self, monkeypatch):
        self.given_a_capturing_root_handler(monkeypatch)
        self.given_an_archive_writer()
        func.configure_stdout_logging("INFO")
        logger = structlog.get_logger("test_service")
        logger.info("first event", body={"text": "x" * 10_000})
        func.set_log_snapshot_writer(None)
        logger.info("second event", body={"text": "y" * 10_000})
        first, second = map(json.loads, self.stream.getvalue().splitlines())
        assert first["log_snapshot_state"] == "stored"
        assert second["log_snapshot_state"] == "not_configured"
        assert second["body"]["text"] == "y" * 10_000
        assert len(self.archive.records) == 1

    def test_snapshot_contains_the_previously_redacted_log_event(self, monkeypatch):
        self.given_a_capturing_root_handler(monkeypatch)
        self.given_an_archive_writer()
        self.when_logging_a_large_event_with_a_redacted_session_field()
        self.then_the_snapshot_contains_only_the_redacted_session_value()

    def test_functions_worker_can_install_its_handler_after_tala_initializes(self, monkeypatch):
        self.given_an_azure_functions_worker_without_an_attached_root_handler(monkeypatch)
        self.when_logging_is_configured_once()
        self.then_tala_leaves_the_root_handler_slot_available()

    def given_an_existing_root_handler(self, monkeypatch):
        monkeypatch.delenv("TDM_LOG_FILE", raising=False)
        monkeypatch.setenv("FUNCTIONS_WORKER_RUNTIME", "python")
        self.root_logger = logging.getLogger()
        self.original_handlers = self.root_logger.handlers[:]
        self.original_level = self.root_logger.level
        self.handler = logging.NullHandler()
        self.original_access_handlers, self.original_access_level, self.original_access_propagate = (
            self.given_saved_access_logger_state()
        )
        self.root_logger.handlers[:] = [self.handler]

    def given_a_capturing_root_handler(self, monkeypatch):
        self.given_an_existing_root_handler(monkeypatch)
        self.stream = StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.root_logger.handlers[:] = [self.handler]

    def given_an_archive_writer(self):
        self.archive = RecordingSnapshotWriter()
        self.previous_archive = func.set_log_snapshot_writer(self.archive)
        self.previous_policy = func.set_log_snapshot_policy(SyntheticDiagnosticPolicy())

    def given_no_archive_writer(self):
        self.previous_archive = func.set_log_snapshot_writer(None)

    def given_a_failing_archive_writer(self):
        self.previous_archive = func.set_log_snapshot_writer(FailingSnapshotWriter())
        self.previous_policy = func.set_log_snapshot_policy(SyntheticDiagnosticPolicy())

    def given_an_azure_functions_worker_without_an_attached_root_handler(self, monkeypatch):
        self.given_an_existing_root_handler(monkeypatch)
        self.root_logger.handlers.clear()

    @staticmethod
    def given_saved_access_logger_state():
        access_logger = logging.getLogger("gunicorn.access")
        return access_logger.handlers[:], access_logger.level, access_logger.propagate

    def when_logging_is_configured_twice(self):
        func.configure_stdout_logging("INFO")
        func.configure_stdout_logging("INFO")

    def when_logging_is_configured_once(self):
        func.configure_stdout_logging("INFO")

    def when_logging_a_request_with_a_large_body(self):
        func.configure_stdout_logging("INFO")
        structlog.get_logger("test_service").bind(
            request_id="request-123", session_id="session-456"
        ).info(
            "sending downstream request", body={"text": "å" * 10_000}
        )

    def when_logging_a_large_event_with_a_redacted_session_field(self):
        func.configure_stdout_logging("INFO")
        structlog.get_logger("test_service").info(
            "oversized event", body={
                "text": "x" * 10_000,
                "session": {
                    "ndu": "private prompt",
                    "turn_counter": 3
                }
            }
        )

    def then_the_existing_handler_is_preserved_once(self):
        assert self.root_logger.handlers == [self.handler]

    def then_tala_leaves_the_root_handler_slot_available(self):
        assert self.root_logger.handlers == []

    def then_the_captured_record_is_bounded_json_with_request_context(self):
        record = json.loads(self.stream.getvalue().strip())
        assert record["event"] == "sending downstream request"
        assert record["request_id"] == "request-123"
        assert record["session_id"] == "session-456"
        assert record["log_snapshot_state"] == "stored"
        snapshot_id = record["log_snapshot_id"]
        assert self.archive.records[snapshot_id]["body"] == {"text": "å" * 10_000}
        assert len(self.stream.getvalue().encode("utf-8")) < func.MAX_LOG_RECORD_BYTES + 100

    def then_the_large_body_is_preserved_with_unavailable_archive_status(self):
        record = json.loads(self.stream.getvalue().strip())
        assert record["body"] == {"text": "å" * 10_000}
        assert record["log_snapshot_state"] == "not_configured"

    def then_the_large_body_is_preserved_with_failed_archive_status(self):
        record = json.loads(self.stream.getvalue().strip())
        assert record["body"] == {"text": "å" * 10_000}
        assert record["log_snapshot_state"] == "failed"
        assert record["log_snapshot_error"] == "RuntimeError"

    def then_the_snapshot_contains_only_the_redacted_session_value(self):
        record = json.loads(self.stream.getvalue().strip())
        snapshot = self.archive.records[record["log_snapshot_id"]]
        assert snapshot["body"]["session"] == {"ndu": "[REDACTED]", "turn_counter": 3}
        assert "private prompt" not in self.archive.serialized[record["log_snapshot_id"]]

    def teardown_method(self):
        access_logger = logging.getLogger("gunicorn.access")
        self.root_logger.handlers[:] = self.original_handlers
        self.root_logger.setLevel(self.original_level)
        access_logger.handlers[:] = self.original_access_handlers
        access_logger.setLevel(self.original_access_level)
        access_logger.propagate = self.original_access_propagate
        if hasattr(self, "previous_archive"):
            func.set_log_snapshot_writer(self.previous_archive)
        try:
            previous_policy = self.previous_policy
        except AttributeError:
            pass
        else:
            func.set_log_snapshot_policy(previous_policy)
