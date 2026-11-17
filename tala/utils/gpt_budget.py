from dataclasses import asdict, dataclass
import json
import math
import operator
import os
import time
import threading
import uuid


POLICY_SETTING = "GPT_REQUEST_POLICIES"
BUDGET_PROTOCOL = 1


def positive_seconds(value):
    if value is True or value is False:
        raise ValueError("A time budget must be a positive finite number.")
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("A time budget must be a positive finite number.")
    return seconds


@dataclass(frozen=True)
class RetryPolicy:
    assignment_seconds: float
    first_content_seconds: float
    completion_seconds: float
    total_seconds: float
    max_attempts: int

    def __post_init__(self):
        for field in ("assignment_seconds", "first_content_seconds", "completion_seconds", "total_seconds"):
            object.__setattr__(self, field, positive_seconds(self.__dict__[field]))
        if self.max_attempts is True or self.max_attempts is False or operator.index(self.max_attempts) < 1:
            raise ValueError("max_attempts must be a positive integer, including the initial attempt.")


def policy_from_environment(priority, workload="interactive"):
    raw = os.environ.get(POLICY_SETTING)
    if not raw:
        return None
    profiles = json.loads(raw)
    profile = profiles.get(f"{workload}:{priority}")
    return None if profile is None else RetryPolicy(**profile)


class RequestFailure(RuntimeError):
    def __init__(self, phase, reason, *, retryable=False, retry_after=0.0, timings=None, deployment=None,
                 request_id=None, attempt_id=None):
        super().__init__(f"GPT request failed in {phase}: {reason}")
        self.phase = phase
        self.reason = reason
        self.retryable = retryable
        self.retry_after = float(retry_after)
        if not math.isfinite(self.retry_after) or self.retry_after < 0:
            raise ValueError("retry_after must be a non-negative finite number.")
        self.timings = dict(timings or {})
        self.deployment = deployment
        self.request_id = request_id
        self.attempt_id = attempt_id

    def as_dict(self):
        return {
            "phase": self.phase, "reason": self.reason, "retryable": self.retryable,
            "retry_after": self.retry_after, "timings": self.timings, "deployment": self.deployment,
            "request_id": self.request_id, "attempt_id": self.attempt_id,
        }


class RequestBudget:
    def __init__(self, policy, *, priority, workload="interactive", request_id=None,
                 clock=time.monotonic, wall_clock=time.time, sleep=time.sleep):
        self.policy = policy
        self.priority = priority
        self.workload = workload
        self.request_id = request_id or str(uuid.uuid4())
        self.correlation_id = self.request_id
        self.clock = clock
        self.wall_clock = wall_clock
        self.sleep = sleep
        self.deadline = clock() + policy.total_seconds
        self.attempts = 0
        self._attempt_lock = threading.Lock()

    def remaining(self):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise RequestFailure("total", "deadline_exceeded", request_id=self.request_id)
        return remaining

    def fork_request(self, priority=None):
        request_priority = self.priority if priority is None else priority
        child_policy = policy_from_environment(request_priority, self.workload) or self.policy
        child = RequestBudget(child_policy, priority=request_priority, workload=self.workload,
                              clock=self.clock, wall_clock=self.wall_clock, sleep=self.sleep)
        child.deadline = min(self.deadline, child.deadline)
        child.correlation_id = self.correlation_id
        return child

    def begin_attempt(self):
        with self._attempt_lock:
            return self._allocate_attempt()

    def _allocate_attempt(self):
        remaining = self.remaining()
        if self.attempts >= self.policy.max_attempts:
            raise RequestFailure("total", "attempts_exhausted", request_id=self.request_id)
        self.attempts += 1
        return {
            "version": BUDGET_PROTOCOL, "attempt": self.attempts, "attempt_id": str(uuid.uuid4()),
            "request_id": self.request_id, "priority": self.priority, "workload": self.workload,
            "correlation_id": self.correlation_id,
            "deadline_unix_ms": (self.wall_clock() + remaining) * 1000,
            "assignment_seconds": min(self.policy.assignment_seconds, remaining),
            "first_content_seconds": min(self.policy.first_content_seconds, remaining),
            "completion_seconds": min(self.policy.completion_seconds, remaining),
        }

    def forward(self):
        return {"policy": asdict(self.policy), "priority": self.priority, "workload": self.workload,
                "request_id": self.request_id, "correlation_id": self.correlation_id, "attempts": self.attempts,
                "deadline_unix_ms": (self.wall_clock() + self.remaining()) * 1000}

    @classmethod
    def from_forwarded(cls, contract):
        budget = cls(RetryPolicy(**contract["policy"]), priority=contract["priority"], workload=contract["workload"],
                     request_id=contract["request_id"])
        remaining = positive_seconds(contract["deadline_unix_ms"]) / 1000 - budget.wall_clock()
        budget.deadline = min(budget.deadline, budget.clock() + remaining)
        if contract["attempts"] is True or contract["attempts"] is False:
            raise ValueError("A forwarded attempt count must be an integer.")
        budget.attempts = operator.index(contract["attempts"])
        budget.correlation_id = contract.get("correlation_id", budget.request_id)
        if budget.attempts < 0:
            raise ValueError("A forwarded attempt count cannot be negative.")
        budget.remaining()
        return budget

    def can_retry(self, failure):
        return (failure.retryable and self.attempts < self.policy.max_attempts
                and self.deadline - self.clock() > failure.retry_after)


def run_with_retries(operation, budget, on_retry=None):
    while True:
        attempt = budget.begin_attempt()
        try:
            result = operation(attempt)
            budget.remaining()
            return result
        except RequestFailure as failure:
            if not budget.can_retry(failure):
                raise
            if on_retry is not None:
                on_retry(failure)
            if failure.retry_after:
                budget.sleep(failure.retry_after)


def model_failure(error, *, timings=None, deployment=None, request_id=None, attempt_id=None):
    try:
        status = error.status_code
    except AttributeError:
        status = None
    try:
        retry_after = float(error.response.headers.get("retry-after", "0"))
    except (AttributeError, TypeError, ValueError):
        retry_after = 0.0
    if not math.isfinite(retry_after) or retry_after < 0:
        retry_after = 0.0
    return RequestFailure(
        "model", "rate_limited" if status == 429 else "request_failed",
        retryable=status == 429 or (status is not None and status >= 500), retry_after=retry_after,
        timings=timings, deployment=deployment, request_id=request_id, attempt_id=attempt_id,
    )
