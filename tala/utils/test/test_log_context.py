from copy import deepcopy
from unittest.mock import patch

import pytest
import structlog

from tala.utils import func, log_context, requestor


class TestCorrelationHeaders:
    def test_round_trip_preserves_root_identity_and_a_distinct_call_id(self):
        self.given_pipeline_context()
        self.when_headers_are_created_for_a_gpt_call()
        self.then_headers_keep_root_and_local_ids_separate()

    def test_unicode_identifiers_are_encoded_as_ascii_headers(self):
        self.given_pipeline_context(session_id="session-å")
        self.when_headers_are_created_for_a_gpt_call()
        self.then_session_identifier_round_trips_without_raw_non_ascii_headers()

    @pytest.mark.parametrize("invalid_value", ["bad\nvalue", "bad\rvalue", "x" * 257, {"not": "an ID"}])
    def test_invalid_identifiers_are_not_sent(self, invalid_value):
        self.given_pipeline_context(utterance_id=invalid_value)
        self.when_headers_are_created_for_a_gpt_call()
        self.then_invalid_utterance_id_is_absent()

    @pytest.mark.parametrize("header_value", ["bad%0Avalue", "%ff", "%ZZ", "bad%", "x" * 769])
    def test_malformed_received_headers_are_ignored(self, header_value):
        self.given_malformed_incoming_headers(header_value)
        self.when_header_context_is_read()
        self.then_no_invalid_context_is_bound()

    @pytest.mark.parametrize("invalid_turn", [True, -1, 1.5, {"not": "a turn"}])
    def test_invalid_turn_values_are_not_sent(self, invalid_turn):
        self.given_pipeline_context(turn_id=invalid_turn)
        self.when_headers_are_created_for_a_gpt_call()
        assert "X-Tala-Turn-Id" not in self.headers

    def given_pipeline_context(self, **overrides):
        context = {
            "request_id": "pipeline-request",
            "session_id": "session-1",
            "offer_id": "offer-1",
            "utterance_id": "utterance-1",
            "turn_id": 3,
            "attempt_id": "attempt-1",
        }
        context.update(overrides)
        self.logger = structlog.get_logger("synthetic-pipeline").bind(**context)

    def given_malformed_incoming_headers(self, value):
        self.headers = {"X-Tala-Utterance-Id": value, "Authorization": "not-log-context"}

    def when_headers_are_created_for_a_gpt_call(self):
        self.headers = log_context.correlation_headers(self.logger, request_id="gpt-call-request")
        self.decoded = log_context.correlation_context(self.headers)

    def when_header_context_is_read(self):
        self.decoded = log_context.correlation_context(self.headers)

    def then_headers_keep_root_and_local_ids_separate(self):
        assert self.decoded == {
            "correlation_id": "pipeline-request",
            "request_id": "gpt-call-request",
            "session_id": "session-1",
            "offer_id": "offer-1",
            "utterance_id": "utterance-1",
            "turn_id": 3,
            "attempt_id": "attempt-1",
        }

    def then_session_identifier_round_trips_without_raw_non_ascii_headers(self):
        assert self.decoded["session_id"] == "session-å"
        assert self.headers["X-Tala-Session-Id"].isascii()

    def then_invalid_utterance_id_is_absent(self):
        assert "X-Tala-Utterance-Id" not in self.headers
        assert "utterance_id" not in self.decoded

    def then_no_invalid_context_is_bound(self):
        assert self.decoded == {}


class TestSyntheticUtteranceRequestChain:
    def test_pipeline_ndu_and_requestor_share_an_utterance_without_changing_payloads(self):
        self.given_a_synthetic_utterance_request()
        self.when_request_context_crosses_pipeline_ndu_and_requestor_boundaries()
        self.then_the_same_utterance_and_root_request_can_be_followed()

    def given_a_synthetic_utterance_request(self):
        self.ndu_request = {
            "request_id": "pipeline-request",
            "session": {
                "session_id": "session-1",
                "offer_id": "offer-1",
                "turn_counter": 3
            },
            "hypotheses": [{
                "utterance": "unique synthetic utterance"
            }],
        }
        self.original_request = deepcopy(self.ndu_request)
        self.pipeline_logger = structlog.get_logger("synthetic-pipeline").bind(
            request_id="pipeline-request",
            utterance_id="utterance-1",
            attempt_id="pipeline-attempt",
            turn_id=3,
            session_id="session-1",
            offer_id="offer-1"
        )

    def when_request_context_crosses_pipeline_ndu_and_requestor_boundaries(self):
        self.ndu_headers = log_context.correlation_headers(self.pipeline_logger, request_id="pipeline-request")
        self.ndu = func.FuncBase()
        self.ndu._setup_logger(self.ndu_request, structlog.get_logger("synthetic-ndu"), headers=self.ndu_headers)
        self.requestor_headers = log_context.correlation_headers(self.ndu.logger, request_id="gpt-call-request")
        self.requestor = func.FuncBase()
        self.requestor._setup_logger({"request_id": "gpt-call-request"},
                                     structlog.get_logger("synthetic-requestor"),
                                     headers=self.requestor_headers)

    def then_the_same_utterance_and_root_request_can_be_followed(self):
        context = structlog.get_context(self.requestor.logger)
        assert context["correlation_id"] == "pipeline-request"
        assert context["request_id"] == "gpt-call-request"
        assert context["utterance_id"] == "utterance-1"
        assert context["attempt_id"] == "pipeline-attempt"
        assert context["turn_id"] == 3
        assert context["session_id"] == "session-1"
        assert self.ndu_request == self.original_request
        assert "unique synthetic utterance" not in str(self.ndu_headers)
        assert "unique synthetic utterance" not in str(self.requestor_headers)


class TestRequestorHTTPContext:
    def test_requestor_client_sends_context_headers_without_changing_the_body(self):
        self.given_a_request_and_bound_ndu_logger()
        self.when_a_requestor_http_call_is_made()
        self.then_the_call_has_text_free_context_and_an_unchanged_body()

    def given_a_request_and_bound_ndu_logger(self):
        self.payload = {"request_id": "gpt-call-request", "gpt_request": {"messages": [{"content": "synthetic text"}]}}
        self.original_payload = deepcopy(self.payload)
        self.logger = structlog.get_logger("synthetic-ndu").bind(
            correlation_id="pipeline-request",
            request_id="pipeline-request",
            utterance_id="utterance-1",
            attempt_id="pipeline-attempt",
            turn_id=3
        )

    def when_a_requestor_http_call_is_made(self):
        with patch.object(requestor.requests_session, "post", return_value=SyntheticHTTPResponse()) as post:
            self.response = requestor.make_request(
                "https://requestor.example/api/make-request", self.payload, 1, self.logger
            )
        self.sent = post.call_args.kwargs

    def then_the_call_has_text_free_context_and_an_unchanged_body(self):
        context = log_context.correlation_context(self.sent["headers"])
        assert context["correlation_id"] == "pipeline-request"
        assert context["request_id"] == "gpt-call-request"
        assert context["utterance_id"] == "utterance-1"
        assert context["attempt_id"] == "pipeline-attempt"
        assert context["turn_id"] == 3
        assert self.sent["json"] == self.original_payload
        assert self.payload == self.original_payload
        assert "synthetic text" not in str(self.sent["headers"])
        assert self.response == {"ok": True}


class SyntheticHTTPResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": True}
