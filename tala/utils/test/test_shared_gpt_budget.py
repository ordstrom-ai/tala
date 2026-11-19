from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from tala.utils.gpt_budget import RequestBudget, RequestFailure, RetryPolicy, run_with_retries


@pytest.fixture(autouse=True)
def given_unconfigured_request_policies(monkeypatch):
    monkeypatch.delenv("GPT_REQUEST_POLICIES", raising=False)


class TestSharedAttemptAllowance:
    @pytest.mark.parametrize("used_attempts", [1, 2])
    def test_forwarding_includes_attempts_used_by_preliminary_calls(self, used_attempts):
        self.given_a_workflow_with_two_permitted_attempts()
        self.when_a_preliminary_call_uses_attempts(used_attempts)
        self.when_the_remaining_allowance_is_forwarded()
        self.then_the_downstream_allowance_cannot_restart_the_counter(used_attempts)

    def given_a_workflow_with_two_permitted_attempts(self):
        self.budget = RequestBudget(RetryPolicy(1, 1, 1, 10, 2), priority=1)
        self.child = self.budget.fork_request()

    def when_a_preliminary_call_uses_attempts(self, count):
        self.preliminary_attempts = [self.child.begin_attempt() for _ in range(count)]

    def when_the_remaining_allowance_is_forwarded(self):
        self.contract = json.loads(json.dumps(self.budget.forward()))
        self.downstream = RequestBudget.from_forwarded(self.contract)
        self.downstream_attempts = []
        try:
            while True:
                self.downstream_attempts.append(self.downstream.begin_attempt())
        except RequestFailure as error:
            self.failure = error

    def then_the_downstream_allowance_cannot_restart_the_counter(self, used):
        assert self.budget.attempts == used
        assert self.contract["attempts"] == used
        assert len(self.downstream_attempts) == 2 - used
        assert self.failure.reason == "attempts_exhausted"
        assert self.contract["correlation_id"] == self.child.correlation_id
        assert self.child.request_id != self.budget.request_id

    def test_a_child_priority_profile_cannot_expand_the_workflow_allowance(self, monkeypatch):
        self.given_a_workflow_with_two_permitted_attempts()
        self.given_a_child_profile_with_more_attempts(monkeypatch)
        self.when_the_child_profile_exhausts_its_allowance()
        self.then_the_parent_limit_and_requested_priority_are_preserved()

    def given_a_child_profile_with_more_attempts(self, monkeypatch):
        monkeypatch.setenv(
            "GPT_REQUEST_POLICIES",
            json.dumps({
                "interactive:2": {
                    "assignment_seconds": 1,
                    "first_content_seconds": 1,
                    "completion_seconds": 1,
                    "total_seconds": 10,
                    "max_attempts": 5,
                }
            })
        )

    def when_the_child_profile_exhausts_its_allowance(self):
        self.failure = None
        self.child = self.budget.fork_request(2)
        self.when_a_preliminary_call_uses_attempts(2)
        try:
            self.child.begin_attempt()
        except RequestFailure as error:
            self.failure = error

    def then_the_parent_limit_and_requested_priority_are_preserved(self):
        assert self.failure is not None, "The child exceeded the workflow attempt limit."
        assert self.failure.reason == "attempts_exhausted"
        assert self.budget.attempts == 2
        assert {attempt["priority"] for attempt in self.preliminary_attempts} == {2}
        assert not self.child.can_retry(RequestFailure("model", "completion_timeout", retryable=True))

    def test_concurrent_children_share_one_atomic_attempt_limit(self):
        self.given_eight_children_with_three_shared_attempts()
        self.when_the_children_request_attempts_concurrently()
        self.then_only_three_distinct_attempts_are_allocated()

    def given_eight_children_with_three_shared_attempts(self):
        self.budget = RequestBudget(RetryPolicy(1, 1, 1, 10, 3), priority=1)
        self.children = [self.budget.fork_request() for _ in range(8)]

    def when_the_children_request_attempts_concurrently(self):
        def allocate(child):
            try:
                return child.begin_attempt(), None
            except RequestFailure as error:
                return None, error

        with ThreadPoolExecutor(max_workers=8) as pool:
            self.outcomes = list(pool.map(allocate, self.children))

    def then_only_three_distinct_attempts_are_allocated(self):
        attempts = [attempt for attempt, error in self.outcomes if error is None]
        failures = [error for attempt, error in self.outcomes if attempt is None]
        assert self.budget.attempts == 3
        assert len(attempts) == 3
        assert {attempt["attempt"] for attempt in attempts} == {1, 2, 3}
        assert len({attempt["attempt_id"] for attempt in attempts}) == 3
        assert len(failures) == 5
        assert all(error.reason == "attempts_exhausted" for error in failures)


class TestRetryScheduling:
    def test_an_expired_rate_limit_wait_cannot_start_the_reserved_attempt(self):
        self.given_a_rate_limited_request_whose_wait_exceeds_the_deadline()
        self.when_the_caller_runs_the_rate_limited_request()
        self.then_the_reserved_retry_does_not_invoke_the_model()

    def given_a_rate_limited_request_whose_wait_exceeds_the_deadline(self):
        self.now = 0.0
        self.calls = []
        self.waits = []
        self.failure = None

        def delayed_wait(seconds):
            self.waits.append(seconds)
            self.now = 11.0

        self.budget = RequestBudget(RetryPolicy(1, 1, 1, 10, 2), priority=1, clock=lambda: self.now, sleep=delayed_wait)

    def when_the_caller_runs_the_rate_limited_request(self):
        def model(attempt):
            self.calls.append(attempt)
            raise RequestFailure("model", "rate_limited", retryable=True, retry_after=1)

        try:
            run_with_retries(model, self.budget)
        except RequestFailure as error:
            self.failure = error

    def then_the_reserved_retry_does_not_invoke_the_model(self):
        assert len(self.calls) == 1
        assert self.waits == [1]
        assert self.failure.phase == "total"
        assert self.failure.reason == "deadline_exceeded"

    def test_a_competing_call_cannot_leave_a_filler_notification_without_a_retry(self, monkeypatch):
        self.given_a_retry_check_that_loses_the_last_attempt_to_another_call(monkeypatch)
        self.when_a_model_failure_requests_a_retry()
        self.then_the_original_failure_is_preserved_without_an_unallocated_retry()

    def given_a_retry_check_that_loses_the_last_attempt_to_another_call(self, monkeypatch):
        self.given_a_request_with_a_classified_model_failure()
        self.competitor = self.budget.fork_request()
        can_retry = self.budget.can_retry

        def retry_check(failure):
            permitted = can_retry(failure)
            self.competitor.begin_attempt()
            return permitted

        monkeypatch.setattr(self.budget, "can_retry", retry_check)

    def given_a_request_with_a_classified_model_failure(self):
        self.budget = RequestBudget(RetryPolicy(1, 1, 1, 10, 2), priority=1)
        self.notifications = []
        self.calls = []
        self.failure = None
        self.initial_failure = RequestFailure(
            "model",
            "completion_timeout",
            retryable=True,
            request_id=self.budget.request_id,
            deployment={
                "name": "test-model",
                "resource": "test-resource"
            },
            timings={
                "assignment_seconds": 0.1,
                "model_seconds": 1
            },
        )

    def when_a_model_failure_requests_a_retry(self):
        def model(attempt):
            self.calls.append(attempt)
            self.initial_failure.attempt_id = attempt["attempt_id"]
            raise self.initial_failure

        try:
            run_with_retries(model, self.budget, self.notifications.append)
        except RequestFailure as error:
            self.failure = error

    def then_the_original_failure_is_preserved_without_an_unallocated_retry(self):
        assert len(self.calls) == 1
        assert self.budget.attempts == 2
        assert self.notifications == []
        assert self.failure is self.initial_failure
        assert self.failure.phase == "model"
        assert self.failure.reason == "completion_timeout"
        self.then_the_failed_attempt_context_is_retained()

    def then_the_failed_attempt_context_is_retained(self):
        assert self.failure.request_id == self.calls[0]["request_id"]
        assert self.failure.attempt_id == self.calls[0]["attempt_id"]
        assert self.failure.deployment == {"name": "test-model", "resource": "test-resource"}
        assert self.failure.timings == {"assignment_seconds": 0.1, "model_seconds": 1}

    def test_deadline_expiry_during_reservation_keeps_the_failed_attempt_context(self, monkeypatch):
        self.given_a_retry_check_whose_total_deadline_expires(monkeypatch)
        self.when_a_model_failure_requests_a_retry()
        self.then_total_expiry_keeps_the_original_failure_as_its_cause()

    def given_a_retry_check_whose_total_deadline_expires(self, monkeypatch):
        self.given_a_request_with_a_classified_model_failure()
        can_retry = self.budget.can_retry

        def retry_check(failure):
            permitted = can_retry(failure)
            self.budget.deadline = self.budget.clock() - 1
            return permitted

        monkeypatch.setattr(self.budget, "can_retry", retry_check)

    def then_total_expiry_keeps_the_original_failure_as_its_cause(self):
        assert len(self.calls) == 1
        assert self.notifications == []
        assert self.failure.phase == "total"
        assert self.failure.reason == "deadline_exceeded"
        assert not self.failure.retryable
        assert self.failure.__cause__ is self.initial_failure
        self.then_the_failed_attempt_context_is_retained()
