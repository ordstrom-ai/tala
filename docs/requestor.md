# Requestor client

Tala’s `GPTRequest` class sends language-model requests to the platform’s
Requestor service. It communicates with that service; it does not call a model
provider directly.

## Configure the Requestor endpoint

Set `FUNCTION_ENDPOINT_REQUESTOR` in the environment of the process that runs
your Python code. Its value must be the URL of an accessible Requestor endpoint:

```bash
export FUNCTION_ENDPOINT_REQUESTOR="https://your-requestor-host/your-endpoint"
```

Use a model identifier supported by your Requestor configuration. Tala does not
provision the Requestor service or its model deployment.

## Request structured JSON

Pass an OpenAI-compatible JSON Schema response format to `GPTRequest`. Calling
`make()` starts the request; reading `json_response` waits for it to finish and
parses the returned JSON.

```python
from tala.utils.requestor import (
    GPTContentFilterError,
    GPTRequest,
    GPTStructuredOutputError,
)

request = GPTRequest(
    messages=[{"role": "user", "content": "Return the status."}],
    model="your-requestor-model",
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "status",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
                "additionalProperties": False,
            },
        },
    },
)
request.make()

try:
    result = request.json_response
except GPTStructuredOutputError as error:
    print(f"Invalid structured response for request {error.request_id}")
except GPTContentFilterError as error:
    print(f"Request {error.request_id} was filtered")
else:
    print(result)

print(request.completion_status)
```

`completion_status` reports the status returned by Requestor, such as
`completed`, `truncated`, `refused`, `incomplete`, or `error`. A malformed JSON
response to a structured-output request raises `GPTStructuredOutputError`,
which includes the request ID.

## Generic JSON mode

For requests using `use_json=True` without a structured `response_format`,
`allow_json_repair` controls a legacy retry that asks the model to repair
invalid JSON. It defaults to `True`; set it to `False` to disable the retry.
Structured responses do not use this repair retry: malformed structured JSON
raises `GPTStructuredOutputError`.

## Opt-in phase-aware budgets (Task #161)

`GPT_REQUEST_POLICIES` is a JSON object keyed by `workload:priority`, for example
`interactive:1` or `background:200`. Each configured profile requires positive
finite `assignment_seconds`, `first_content_seconds`, `completion_seconds`, and
`total_seconds`, plus a positive integer `max_attempts` **including the initial
attempt**. Missing profiles leave legacy behavior selected. No numerical live
defaults are provided; choose values from latency evidence and review them before
enabling a profile. Priority is retained on retries, never escalated automatically.

The assignment budget includes queue, slot and rate-pacing waits. The model clock
starts after assignment, at the provider call. Streaming first content means the
first non-whitespace generated-text delta, not headers, roles, usage, SSE comments
or filler speech. Completion and total deadlines also bound a stream after output
starts. A filler never resets these clocks.

`GPTRequest` selects an interactive profile by default. Use `workload="background"`
for ingestion and an explicit `retry_budget=RequestBudget(...)` when repair calls
or a downstream service must share a deadline and allowance. Each retry/repair
uses a distinct attempt ID under the same logical request ID. Successful results
arriving within the budget remain available even when read later.

`RequestFailure` preserves `phase`, `reason`, `retryable`, `retry_after`, `timings`,
`deployment`, `request_id`, and `attempt_id`. Assignment and model failures are
distinct. A Requestor transport read timeout has an **unknown outcome** and is not
automatically resubmitted, even for legacy clients. A connection timeout before
the request was sent may still be retried. In budgeted mode, permanent model
errors/refusals are not retried unchanged; rate-limit waits require enough
remaining time and attempts.
Successful calls expose timing/deployment/attempt metadata through
`GPTRequest.request_metrics`; failures expose it directly on `RequestFailure`.

Budgeted `GPTRequest.make()` performs the explicit caller-side retries; Requestor
executes one provider attempt with SDK retries disabled. Automatic JSON repair is
disabled in this mode. Callers can deliberately request a correction using the
same `GPTRequest`/budget; that correction consumes the same allowance. A
nonblocking `on_retry(failure)` callback can enqueue NDU's retry filler before the
next model attempt. It must not perform network delivery synchronously.

Direct streaming callers use the same `run_with_retries` budget and async stream
consumer. They retry only before answer content is forwarded; cancellation closes
the local connection and late local output is discarded. This does not guarantee
the provider stops computation or billing. It does not authorize restarting an
already emitted answer or replaying a whole generation/persistence operation.

### Wire protocol and migration

Budgeted Requestor payloads include top-level `gpt_budget` (version 1, absolute
`deadline_unix_ms`, phase limits, priority/workload, request/attempt IDs) and
`gpt_request.budget_protocol=1`. The inner marker makes an old Requestor reject the
request before GPT invocation instead of silently ignoring its deadline. Responses
must include `budget_protocol=1`, `status`, and either `response_body` with timings
or a structured `failure`. A missing marker is a non-retryable protocol failure.

Only durations are compared using monotonic clocks locally. The forwarded absolute
deadline prevents a new service from restarting the total budget; hosts need
synchronized wall clocks. Configure a total budget with room for assignment,
provider attempts, bounded rate waits and transport/response overhead.

Release the updated Tala package first, upgrade Requestor and clients to that
published version, validate the exact coordinated source in staging, then enable
agreed profiles separately. This source change does not publish a package, update
live settings or establish suitable production values. Existing pinned clients
cannot enable this feature until that package upgrade. See each application's
approved release workflow; the broker heartbeat experiment remains separate.
