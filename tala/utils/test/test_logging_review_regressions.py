from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import logging
from queue import Queue
from threading import Event, RLock, Thread
from unittest.mock import Mock

import pytest
import structlog

from tala.utils import func

SNAPSHOT_FIELDS = (
    "log_snapshot_id", "log_snapshot_state", "log_snapshot_bytes", "log_fields_archived", "log_fields_unavailable",
    "log_snapshot_error", "log_snapshot_reason", "log_original_fields"
)


class TestSnapshotMetadataCollisions:
    @pytest.mark.parametrize("field", SNAPSHOT_FIELDS)
    @pytest.mark.parametrize("outcome", ["missing", "denied", "failed", "stored"])
    def test_snapshot_metadata_preserves_conflicting_caller_values(self, monkeypatch, field, outcome):
        self.given_renderer_and_oversized_event(monkeypatch, outcome)
        self.event[field] = {"caller": "original value"}
        self.when_event_is_rendered()
        self.then_collision_is_preserved_and_generated_metadata_is_authoritative(field, outcome)

    @pytest.mark.parametrize("outcome", ["failed", "stored"])
    def test_large_original_wrapper_is_preserved_or_retrievable(self, monkeypatch, outcome):
        self.given_renderer_and_oversized_event(monkeypatch, outcome)
        self.event["log_original_fields"] = {"diagnostic": "y" * 10_000}
        self.when_event_is_rendered()
        if outcome == "stored":
            assert self.parsed["log_original_fields"]["in_snapshot"] is True
            assert self.snapshots[self.parsed["log_snapshot_id"]] == self.original
            assert len(self.rendered.encode("utf-8")) <= func.MAX_LOG_RECORD_BYTES
        else:
            assert self.parsed["log_original_fields"]["log_original_fields"] == self.original["log_original_fields"]
        assert self.event == self.original

    def test_small_caller_metadata_does_not_change(self, monkeypatch):
        self.given_renderer_and_oversized_event(monkeypatch, "stored")
        self.event = {"event": "small", "log_snapshot_state": "caller state", "log_original_fields": {"caller": 1}}
        self.when_event_is_rendered()
        assert self.parsed == self.original
        assert self.snapshots == {}

    def test_wrapper_collision_does_not_bypass_transcript_preservation(self, monkeypatch):
        self.given_renderer_and_oversized_event(monkeypatch, "stored")
        self.renderer.preserve_unarchived_fields = False
        self.event["log_original_fields"] = {"utterance": "synthetic private input" * 1_000}
        self.when_event_is_rendered()
        assert self.parsed["log_snapshot_state"] == "not_permitted"
        assert self.parsed["log_original_fields"]["log_original_fields"] == self.original["log_original_fields"]
        assert self.snapshots == {}
        assert self.event == self.original

    def given_renderer_and_oversized_event(self, monkeypatch, outcome):
        monkeypatch.setattr(func, "_LOG_SNAPSHOT_WRITER", None)
        monkeypatch.setattr(func, "_LOG_SNAPSHOT_POLICY", None)
        self.snapshots = {}
        writer = Mock(spec=["write_snapshot"])

        def store(snapshot_id, content):
            self.snapshots[snapshot_id] = json.loads(content)

        writer.write_snapshot.side_effect = RuntimeError("synthetic failure") if outcome == "failed" else store
        policy = Mock(spec=["permits_snapshot"])
        policy.permits_snapshot.return_value = outcome != "denied"
        self.renderer = func.BoundedJSONRenderer(
            snapshot_writer=None if outcome == "missing" else writer, snapshot_policy=policy
        )
        self.event = {"event": "synthetic diagnostic", "request_id": "request-1", "body": {"diagnostic": "x" * 10_000}}

    def when_event_is_rendered(self):
        self.original = deepcopy(self.event)
        self.rendered = self.renderer(None, None, self.event)
        self.parsed = json.loads(self.rendered)

    def then_collision_is_preserved_and_generated_metadata_is_authoritative(self, field, outcome):
        states = {"missing": "not_configured", "denied": "not_permitted", "failed": "failed", "stored": "stored"}
        assert self.parsed["log_original_fields"] == {field: self.original[field]}
        assert self.parsed["log_snapshot_state"] == states[outcome]
        assert self.parsed["request_id"] == self.original["request_id"]
        assert self.event == self.original
        if outcome == "stored":
            assert self.snapshots[self.parsed["log_snapshot_id"]] == self.original
            assert len(self.rendered.encode("utf-8")) <= func.MAX_LOG_RECORD_BYTES
        else:
            assert self.parsed["body"] == self.original["body"]
            assert self.snapshots == {}


class TestInheritedRootCorrelation:
    @pytest.mark.parametrize(
        "header,expected_root", [(None, "parent-root"), ("header-root", "header-root"), ("bad%0Aroot", "parent-root")]
    )
    def test_explicit_header_or_parent_root_remains_distinct_from_local_request(self, header, expected_root):
        self.given_parent_logger("parent-root")
        self.when_child_logger_is_created(header)
        self.then_child_has_root_and_local_ids_without_changing_parent(expected_root)

    def test_request_id_bootstraps_root_only_when_no_root_is_known(self):
        self.given_parent_logger(None)
        self.when_child_logger_is_created(None)
        self.then_child_has_root_and_local_ids_without_changing_parent("child-request")

    def test_concurrent_children_do_not_mutate_parent_or_leak_local_ids(self):
        self.given_parent_logger("parent-root")

        def create_child(request_id):
            child = func.FuncBase()
            child._setup_logger({"request_id": request_id}, self.parent)
            return structlog.get_context(child.logger)

        with ThreadPoolExecutor(max_workers=2) as pool:
            contexts = list(pool.map(create_child, ["child-1", "child-2"]))
        assert [context["request_id"] for context in contexts] == ["child-1", "child-2"]
        assert all(context["correlation_id"] == "parent-root" for context in contexts)
        assert structlog.get_context(self.parent) == self.parent_context

    def given_parent_logger(self, root):
        context = {"request_id": "parent-request"}
        if root is not None:
            context["correlation_id"] = root
        self.parent = structlog.get_logger("synthetic-parent").bind(**context)
        self.parent_context = deepcopy(structlog.get_context(self.parent))

    def when_child_logger_is_created(self, header):
        self.child = func.FuncBase()
        headers = {"X-Tala-Request-Id": "transport-request"}
        if header is not None:
            headers["X-Tala-Correlation-Id"] = header
        self.child._setup_logger({"request_id": "child-request"}, self.parent, headers=headers)

    def then_child_has_root_and_local_ids_without_changing_parent(self, expected_root):
        assert structlog.get_context(self.child.logger)["correlation_id"] == expected_root
        assert structlog.get_context(self.child.logger)["request_id"] == "child-request"
        assert structlog.get_context(self.parent) == self.parent_context


class ObservedConfigurationLock:
    def __init__(self):
        self.lock = RLock()
        self.attempts = Queue()

    def __enter__(self):
        self.attempts.put(True)
        self.lock.acquire()
        return self

    def __exit__(self, *args):
        self.lock.release()


class TestConcurrentLoggingConfiguration:
    def test_concurrent_configuration_adds_each_handler_once(self, monkeypatch, tmp_path):
        self.given_isolated_loggers_and_blocked_configuration(monkeypatch, tmp_path)
        try:
            self.when_two_initializations_overlap()
            self.then_configuration_has_one_of_each_handler()
        finally:
            self.restore_loggers()

    def test_configuration_failure_releases_the_lock_for_another_thread(self, monkeypatch, tmp_path):
        self.given_isolated_loggers_and_blocked_configuration(monkeypatch, tmp_path)
        finished = Event()

        def initialize():
            try:
                func.configure_stdout_logging("INFO")
            except Exception as error:
                self.errors.append(error)
            finally:
                finished.set()

        try:
            with monkeypatch.context() as patcher:
                patcher.setattr(func, "_create_stdout_handler", Mock(side_effect=OSError("synthetic config failure")))
                with pytest.raises(OSError, match="synthetic config failure"):
                    func.configure_stdout_logging("INFO")
            self.release_factory.set()
            worker = Thread(target=initialize, daemon=True)
            self.workers.append(worker)
            worker.start()
            assert finished.wait(1), "A failed configuration left the lock held"
            worker.join(1)
            assert self.errors == []
            assert not worker.is_alive()
        finally:
            self.restore_loggers()

    def given_isolated_loggers_and_blocked_configuration(self, monkeypatch, tmp_path):
        self.root, self.access = logging.getLogger(), logging.getLogger("gunicorn.access")
        self.original_root = (self.root.handlers[:], self.root.level)
        self.original_access = (self.access.handlers[:], self.access.level, self.access.propagate)
        self.original_structlog = structlog.get_config()
        self.root.handlers[:] = []
        self.access.handlers[:] = []
        monkeypatch.setenv("FUNCTIONS_WORKER_RUNTIME", "")
        self.log_file = str(tmp_path / "synthetic.log")
        monkeypatch.setenv("TDM_LOG_FILE", self.log_file)
        self.factory_entered, self.release_factory = Event(), Event()
        self.configuration_lock = ObservedConfigurationLock()
        monkeypatch.setattr(func, "_LOGGING_CONFIGURATION_LOCK", self.configuration_lock, raising=False)
        original_factory = func._create_stdout_handler

        def blocked_factory():
            self.factory_entered.set()
            assert self.release_factory.wait(2)
            return original_factory()

        self.factory = Mock(side_effect=blocked_factory)
        monkeypatch.setattr(func, "_create_stdout_handler", self.factory)
        self.errors = []
        self.workers = []

    def when_two_initializations_overlap(self):
        def initialize():
            try:
                func.configure_stdout_logging("INFO")
            except Exception as error:
                self.errors.append(error)

        for _ in range(2):
            worker = Thread(target=initialize)
            self.workers.append(worker)
            worker.start()
            assert self.configuration_lock.attempts.get(timeout=1)
            assert self.factory_entered.wait(1)
        assert self.factory.call_count == 1
        self.release_factory.set()
        for worker in self.workers:
            worker.join(1)

    def then_configuration_has_one_of_each_handler(self):
        assert self.errors == []
        assert all(not worker.is_alive() for worker in self.workers)
        assert self.factory.call_count == 1
        assert len(self.root.handlers) == 2  # one stdout and one file handler
        assert sum(getattr(handler, "baseFilename", None) == self.log_file for handler in self.root.handlers) == 1
        assert len(self.access.handlers) == 1

    def restore_loggers(self):
        self.release_factory.set()
        for worker in self.workers:
            worker.join(2)
        for handler in self.root.handlers + self.access.handlers:
            if handler not in self.original_root[0] + self.original_access[0]:
                handler.close()
        self.root.handlers[:] = self.original_root[0]
        self.root.setLevel(self.original_root[1])
        self.access.handlers[:] = self.original_access[0]
        self.access.setLevel(self.original_access[1])
        self.access.propagate = self.original_access[2]
        structlog.configure(**self.original_structlog)
