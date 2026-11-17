from types import SimpleNamespace

import pytest
import requests
import structlog

from tala.utils.gpt_budget import RequestBudget, RequestFailure, RetryPolicy
from tala.utils import requestor


class TestBudgetedRequestorClient:
    @pytest.mark.parametrize("first_failure,expected_calls", [
        ("model_timeout", 2), ("read_timeout", 1), ("connection_reset", 1), ("old_protocol", 1),
    ])
    def test_only_classified_safe_failures_can_trigger_another_request(self, monkeypatch, first_failure, expected_calls):
        self.given_a_budgeted_client_and_controlled_requestor_responses(monkeypatch, first_failure)
        self.when_the_caller_requests_an_answer()
        self.then_requests_and_retry_notifications_are_bounded(expected_calls)

    def given_a_budgeted_client_and_controlled_requestor_responses(self, monkeypatch, first_failure):
        self.calls = []
        self.retry_notifications = []
        self.error = None
        self.result = None
        self.budget = RequestBudget(RetryPolicy(1, 1, 1, 5, 2), priority=1)
        self.client = requestor.GPTRequest(retry_budget=self.budget, logger=structlog.get_logger(),
                                           on_retry=self.retry_notifications.append)

        def post(endpoint, **arguments):
            self.calls.append(arguments)
            if len(self.calls) == 1:
                if first_failure == "read_timeout":
                    raise requests.ReadTimeout("response not known")
                if first_failure == "connection_reset":
                    raise requests.ConnectionError("connection lost; response not known")
                if first_failure == "old_protocol":
                    result = {"status": "failure"}
                else:
                    result = {"budget_protocol": 1, "status": "failure", "failure": RequestFailure(
                        "model", "completion_timeout", retryable=True,
                        timings={"assignment_seconds": 0.01, "model_seconds": 1},
                    ).as_dict()}
            else:
                result = {"budget_protocol": 1, "status": "success", "response_body": '{"answer":"ok"}',
                          "completion_status": "completed"}
            return SimpleNamespace(json=lambda: result, close=lambda: None)

        monkeypatch.setattr(requestor.requests_session, "post", post)

    def when_the_caller_requests_an_answer(self):
        self.client.make()
        try:
            self.result = self.client.json_response
        except RequestFailure as error:
            self.error = error

    def then_requests_and_retry_notifications_are_bounded(self, calls):
        assert len(self.calls) == calls
        assert len(self.retry_notifications) == calls - 1
        assert self.client._done.is_set()
        assert {call["json"]["request_id"] for call in self.calls} == {self.budget.request_id}
        assert all(call["json"]["gpt_request"]["max_retries"] == 0 for call in self.calls)
        assert all(call["json"]["gpt_request"]["budget_protocol"] == 1 for call in self.calls)
        if calls == 2:
            assert self.result == {"answer": "ok"}
            assert self.retry_notifications[0].phase == "model"
        else:
            assert self.error is not None
            assert not self.error.retryable

    @pytest.mark.parametrize("error_class", [requests.ReadTimeout, requests.ConnectionError])
    def test_legacy_transport_failures_are_not_blindly_resubmitted(self, monkeypatch, error_class):
        self.given_a_legacy_post_with_an_unknown_outcome(monkeypatch, error_class)
        self.when_the_legacy_transport_sends_the_request()
        self.then_no_second_post_is_made()

    def given_a_legacy_post_with_an_unknown_outcome(self, monkeypatch, error_class):
        self.calls = []
        self.error = None

        def post(*args, **arguments):
            self.calls.append(arguments)
            raise error_class("Outcome unknown")

        monkeypatch.setattr(requestor.requests_session, "post", post)

    def when_the_legacy_transport_sends_the_request(self):
        try:
            requestor.make_request("https://example.invalid", {"request_id": "legacy-test"}, 1, structlog.get_logger())
        except requestor.ConnectionException as error:
            self.error = error

    def then_no_second_post_is_made(self):
        assert len(self.calls) == 1
        assert self.error is not None

    def test_a_connect_timeout_can_be_retried_before_the_request_is_sent(self, monkeypatch):
        self.given_a_connection_setup_that_recovers(monkeypatch)
        self.when_a_request_is_made()
        self.then_the_successful_response_follows_one_safe_reconnect()

    def given_a_connection_setup_that_recovers(self, monkeypatch):
        self.calls = []

        def post(*args, **arguments):
            self.calls.append(arguments)
            if len(self.calls) == 1:
                raise requests.ConnectTimeout("Connection was not established")
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"response_body": "ok"}, text="")

        monkeypatch.setattr(requestor.requests_session, "post", post)

    def when_a_request_is_made(self):
        self.response = requestor.make_request("https://example.invalid", {"request_id": "connect-test"}, 1,
                                               structlog.get_logger())

    def then_the_successful_response_follows_one_safe_reconnect(self):
        assert len(self.calls) == 2
        assert self.response["response_body"] == "ok"
