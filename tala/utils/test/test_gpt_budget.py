import asyncio
from types import SimpleNamespace

import pytest

from tala.utils.gpt_budget import RequestBudget, RequestFailure, RetryPolicy, policy_from_environment, run_with_retries
from tala.utils.gpt_stream import consume_model_stream


class TestRequestBudget:
    @pytest.mark.parametrize("retryable,attempts,expected_calls", [(True, 2, 2), (False, 2, 1), (True, 1, 1)])
    def test_retry_ownership_is_bounded(self, retryable, attempts, expected_calls):
        self.given_a_policy_and_an_initial_failure(retryable, attempts)
        self.when_the_caller_runs_the_request()
        self.then_the_attempt_limit_and_request_identity_are_preserved(expected_calls)

    def given_a_policy_and_an_initial_failure(self, retryable, attempts):
        self.now = 0.0
        self.calls = []
        self.retry_callbacks = []
        policy = RetryPolicy(1, 2, 3, 10, attempts)
        self.budget = RequestBudget(policy, priority=200, workload="background", clock=lambda: self.now)
        self.failure = RequestFailure("model", "completion_timeout", retryable=retryable)
        self.error = None
        self.result = None

    def when_the_caller_runs_the_request(self):
        def request(attempt):
            self.calls.append(attempt)
            if len(self.calls) == 1:
                raise self.failure
            return "answer"

        try:
            self.result = run_with_retries(request, self.budget, self.retry_callbacks.append)
        except RequestFailure as error:
            self.error = error

    def then_the_attempt_limit_and_request_identity_are_preserved(self, expected_calls):
        assert len(self.calls) == expected_calls
        assert len(self.retry_callbacks) == expected_calls - 1
        assert {call["priority"] for call in self.calls} == {200}
        assert len({call["request_id"] for call in self.calls}) == 1
        assert len({call["attempt_id"] for call in self.calls}) == expected_calls
        assert (self.result == "answer") == (expected_calls == 2)
        if expected_calls == 2:
            assert self.error is None
        else:
            assert self.error is self.failure

    def test_a_rate_limit_wait_cannot_extend_the_total_deadline(self):
        self.given_a_policy_and_an_initial_failure(True, 2)
        self.given_a_retry_wait_longer_than_the_remaining_budget()
        self.when_the_caller_runs_the_request()
        self.then_the_attempt_limit_and_request_identity_are_preserved(1)

    def given_a_retry_wait_longer_than_the_remaining_budget(self):
        self.failure = RequestFailure("model", "rate_limited", retryable=True, retry_after=11)

    def test_a_rate_limit_wait_within_the_deadline_allows_one_bounded_retry(self):
        self.given_a_budget_with_a_controlled_rate_limit_wait()
        self.when_the_rate_limited_request_retries()
        self.then_the_retry_uses_one_remaining_attempt()

    def given_a_budget_with_a_controlled_rate_limit_wait(self):
        self.now = 0.0
        self.calls = []
        self.retry_callbacks = []
        self.waits = []

        def advance_time(seconds):
            self.waits.append(seconds)
            self.now += seconds

        self.budget = RequestBudget(
            RetryPolicy(1, 1, 1, 10, 2), priority=1, clock=lambda: self.now, sleep=advance_time
        )

    def when_the_rate_limited_request_retries(self):
        def request(attempt):
            self.calls.append(attempt)
            if len(self.calls) == 1:
                raise RequestFailure("model", "rate_limited", retryable=True, retry_after=2)
            return "answer"

        self.result = run_with_retries(request, self.budget, self.retry_callbacks.append)

    def then_the_retry_uses_one_remaining_attempt(self):
        assert self.result == "answer"
        assert self.now == 2
        assert self.waits == [2]
        assert len(self.calls) == 2
        assert self.budget.attempts == 2
        assert len(self.retry_callbacks) == 1
        assert self.retry_callbacks[0].reason == "rate_limited"
        assert len({attempt["request_id"] for attempt in self.calls}) == 1
        assert len({attempt["attempt_id"] for attempt in self.calls}) == 2

    def test_missing_profiles_leave_live_budgets_unconfigured(self, monkeypatch):
        self.given_no_priority_profiles(monkeypatch)
        self.when_selecting_an_interactive_policy()
        self.then_no_budget_is_implicitly_enabled()

    def given_no_priority_profiles(self, monkeypatch):
        monkeypatch.delenv("GPT_REQUEST_POLICIES", raising=False)

    def when_selecting_an_interactive_policy(self):
        self.selected_policy = policy_from_environment(1)

    def then_no_budget_is_implicitly_enabled(self):
        assert self.selected_policy is None

    def test_a_result_arriving_after_the_total_deadline_is_rejected(self):
        self.given_a_policy_and_an_initial_failure(True, 2)
        self.when_the_model_returns_a_late_result()
        self.then_the_late_result_is_not_accepted_or_retried()

    def when_the_model_returns_a_late_result(self):
        def late_model(attempt):
            self.calls.append(attempt)
            self.now = 11.0
            return "late answer"

        try:
            self.result = run_with_retries(late_model, self.budget)
        except RequestFailure as error:
            self.error = error

    def then_the_late_result_is_not_accepted_or_retried(self):
        assert self.result is None
        assert len(self.calls) == 1
        assert self.error.phase == "total"
        assert not self.error.retryable


class TestFirstGeneratedContent:
    @pytest.mark.parametrize(
        "empty_content,role", [(None, None), ("", None), (" ", None), (None, "assistant")]
    )
    def test_empty_or_role_only_protocol_messages_do_not_satisfy_the_model_deadline(self, empty_content, role):
        self.given_a_model_stream_with_no_generated_text(empty_content, role)
        self.when_waiting_for_the_first_content()
        self.then_the_request_is_cancelled_without_forwarding_output()

    def given_a_model_stream_with_no_generated_text(self, empty_content, role):
        self.messages = []
        self.closed = False
        self.cancelled = False
        self.error = None
        scenario = self

        class SlowStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                if not scenario.messages:
                    scenario.messages.append(empty_content)
                    return SimpleNamespace(choices=[SimpleNamespace(
                        delta=SimpleNamespace(content=empty_content, role=role), finish_reason=None,
                    )])
                try:
                    await asyncio.Event().wait()
                finally:
                    scenario.cancelled = True

            async def close(self):
                scenario.closed = True

        self.stream = SlowStream()
        self.forwarded = []

    def when_waiting_for_the_first_content(self):
        async def open_stream():
            return self.stream

        try:
            asyncio.run(consume_model_stream(open_stream, self.forwarded.append, first_content_seconds=0.02,
                                             completion_seconds=1, remaining=lambda: 1))
        except RequestFailure as error:
            self.error = error

    def then_the_request_is_cancelled_without_forwarding_output(self):
        assert self.error.phase == "model"
        assert self.error.reason == "first_content_timeout"
        assert self.error.retryable
        assert self.closed
        assert self.cancelled
        assert self.forwarded == []
