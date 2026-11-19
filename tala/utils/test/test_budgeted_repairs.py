import json
from types import SimpleNamespace

import pytest

from tala.utils.gpt_budget import RequestBudget, RequestFailure, RetryPolicy
from tala.utils import requestor


class TestBudgetedRepairs:
    @pytest.mark.parametrize("max_attempts", [1, 2])
    def test_an_explicit_json_correction_uses_the_original_attempt_allowance(self, monkeypatch, max_attempts):
        self.given_a_budgeted_request_with_an_invalid_json_answer(monkeypatch, max_attempts)
        self.when_the_initial_answer_is_read()
        self.when_the_caller_requests_an_explicit_correction()
        self.then_the_correction_is_bounded_by_the_same_request_budget(max_attempts)

    def given_a_budgeted_request_with_an_invalid_json_answer(self, monkeypatch, max_attempts):
        self.calls = []
        self.failure = None
        self.decoding_error = None
        self.answer = None
        self.budget = RequestBudget(RetryPolicy(1, 1, 1, 10, max_attempts), priority=1)
        self.client = requestor.GPTRequest(use_json=True, priority=2, retry_budget=self.budget)

        def post(endpoint, **arguments):
            self.calls.append(json.loads(json.dumps(arguments["json"])))
            content = "invalid JSON" if len(self.calls) == 1 else '{"answer":"corrected"}'
            return SimpleNamespace(
                json=lambda: {
                    "budget_protocol": 1,
                    "status": "success",
                    "response_body": content,
                },
                close=lambda: None
            )

        monkeypatch.setattr(requestor.requests_session, "post", post)

    def when_the_initial_answer_is_read(self):
        self.client.make()
        try:
            self.client.json_response
        except requestor.GPTStructuredOutputError as error:
            self.decoding_error = error
        self.initial_call_count = len(self.calls)

    def when_the_caller_requests_an_explicit_correction(self):
        self.client.update_with_last_assistant_and_next_user_message("Return valid JSON only.")
        try:
            self.client.make()
            self.answer = self.client.json_response
        except RequestFailure as error:
            self.failure = error

    def then_the_correction_is_bounded_by_the_same_request_budget(self, attempts):
        assert self.decoding_error is not None
        assert self.initial_call_count == 1
        assert len(self.calls) == attempts
        assert self.budget.attempts == attempts
        assert {call["request_id"] for call in self.calls} == {self.budget.request_id}
        assert len({call["gpt_budget"]["attempt_id"] for call in self.calls}) == attempts
        assert all(call["gpt_request"]["max_retries"] == 0 for call in self.calls)
        assert all(call["priority"] == call["gpt_budget"]["priority"] == 1 for call in self.calls)
        if attempts == 2:
            assert self.failure is None
            assert self.answer == {"answer": "corrected"}
            assert self.calls[-1]["gpt_request"]["messages"][-1]["content"] == "Return valid JSON only."
        else:
            assert self.answer is None
            assert self.failure.reason == "attempts_exhausted"
