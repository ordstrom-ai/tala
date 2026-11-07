# Interaction testing

## Purpose
The interaction testing helpers validate multi-turn dialog flows by comparing
expected moves with recorded responses from the TDM service. These tests are
used in `tala/testing/interaction/test` and rely on the interaction tester to
send requests and assert structured responses.

## Key modules
- `interaction_tester.py`: sends requests to TDM and returns structured output.
- `comparison.py`: compares actual moves with expected sequences and reports
  mismatches.
- `interaction_test_executor.py`: coordinates running scripted interactions.
- `stream_listener.py`: listens to streamed responses where applicable.

## Running tests
Use pytest as usual:

```bash
python -m pytest tala/testing/interaction/test
```

## Configuration
- `TDM_REQUEST_TIMEOUT_SECONDS`: request timeout for interaction tests and the
  TDM client. Defaults to `120` seconds when unset or invalid.

## Adding tests
1. Create a new test module under `tala/testing/interaction/test`.
2. Build expected move sequences that match the structured output for each
   interaction step.
3. Use the interaction tester/executor helpers for request execution.
4. Keep tests deterministic by asserting only on stable fields.

## Expectations
Interaction comparisons can accept a single expected move list or a list of
alternative move sequences. When multiple alternatives are provided, the first
matching sequence is used for the assertion output.

## Format
Interaction tests live in `ddds/<name>/test/interaction_tests.json` and are a
JSON array of test cases. Each test case defines a `name`, `url`, `target_ddd`,
and an `interaction` list with alternating `user` and `system` entries.

Each interaction entry uses:
- `speaker`: `user` or `system`
- `move_content`: list of semantic move strings (system entries may use
  alternatives by providing a list of move lists)
- `speech_content`: expected system utterance (system entries) or user
  utterance to send as speech input (user entries)
- `utterance`: optional text attached to semantic user input
- `interpretations`: optional list of semantic interpretations for user input
- `entities`: optional entity list used with `interpretations`
- `expected_passivity`: optional boolean on user or system turns

Top-level test case fields:
- `name`: test name for logs
- `url`: TDM endpoint (supports port override in executor)
- `target_ddd`: DDD name for semantic user moves
- `interaction`: ordered list of user/system turns
- `neural`: optional flag passed into the session payload

Example (truncated):

```json
[
  {
    "name": "asking about time",
    "url": "http://localhost:9090/interact",
    "target_ddd": "hello_world",
    "interaction": [
      {
        "speaker": "user",
        "move_content": [
          "ask(?X.current_time(X))"
        ]
      },
      {
        "speaker": "system",
        "move_content": [
          "answer(current_time(\"10:05\"))"
        ]
      }
    ]
  }
]
```

Alternatives are expressed by supplying a list of move sequences in
`move_content`, for example when multiple system responses are acceptable.

### User input variants
You can supply semantic moves, free-form speech, or explicit interpretations.
When `move_content` is present, it takes precedence and `utterance` (if
provided) is attached to the semantic interpretation; `speech_content` is
ignored in that case.

Semantic moves (optionally with `utterance`):

```json
{
  "speaker": "user",
  "move_content": ["answer(hour_to_set(11))"],
  "utterance": "set it to eleven"
}
```

DDD-prefixed semantic moves (prefix overrides `target_ddd`):

```json
{
  "speaker": "user",
  "move_content": ["hello_world:answer(hour_to_set(11))"]
}
```

Speech input:

```json
{
  "speaker": "user",
  "speech_content": "set it to eleven"
}
```

Explicit interpretations (with per-move DDD info):

```json
{
  "speaker": "user",
  "utterance": "set it to eleven",
  "interpretations": [
    {
      "moves": [
        {
          "ddd": "hello_world",
          "semantic_expression": "answer(hour_to_set(11))",
          "perception_confidence": 0.9,
          "understanding_confidence": 0.95
        }
      ],
      "modality": "other"
    }
  ],
  "entities": []
}
```

### System expectations
System entries can assert moves, speech output, or passivity:

When both `move_content` and `speech_content` are provided in a system entry,
the tester asserts both the move list and the utterance.

System `move_content` does not support DDD-prefixed moves because output moves
do not carry DDD metadata. Use plain move expressions for system expectations.

```json
{
  "speaker": "system",
  "move_content": [
    "icm:acc*pos",
    "ask(?X.hour_to_set(X))"
  ],
  "speech_content": "What hour should I set?"
}
```

## Output
The interaction test executor returns a result dictionary with:
- `success`: boolean indicating test outcome
- `failure_description`: mismatch description on failure
- `transcript`: buffered transcript for the run

## Streaming
If the executor runs with streaming enabled, the system utterance can be
populated from the stream listener instead of the HTTP response.

## Incremental progress

Pass an optional `on_event` callback to observe an interaction while it runs:

```python
from tala.testing.interaction.interaction_test_executor import InteractionTestExecutorNoAssert


def show_progress(event):
    if event["event"] == "transcript_delta":
        print(event["data"]["text"], end="", flush=True)


executor = InteractionTestExecutorNoAssert()
executor.run_ng_interaction_test(testcase, offer=offer, on_event=show_progress)
result = executor.result
```

Direct callers can use `InteractionTester(port=None, on_event=show_progress)`
and continue calling `run_testcase(testcase, offer)` as before. `on_event` is
appended to both APIs; existing positional calls and return values are unchanged.
Progress works independently of `use_streaming`. It does not forward individual
speech tokens or provide an HTTP streaming endpoint by itself.

### Callback contract

Events are dictionaries with these fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` for this contract |
| `event` | Event name from the table below |
| `execution_id` | New UUID for each `run_testcase` invocation |
| `testcase_id` | Independent UUID identifying this testcase within that invocation |
| `name` | Scripted testcase name |
| `session_id` | Existing dialogue session identifier; may be reused across repetitions |
| `attempt_index` | One-based repetition index, or `None` at test-level boundaries |
| `attempt_count` | Maximum planned repetitions; early stopping can execute fewer |
| `entry_index` | Zero-based scripted interaction index, or `None` outside an entry |
| `speaker` | `user`, `system`, or `None` outside an entry |
| `sequence` | One-based increasing sequence, reset for each invocation |
| `timestamp` | Unix timestamp in seconds |
| `data` | Event-specific payload |

| Event | Payload |
| --- | --- |
| `test_started` | `entry_count` (`None` for an iterable without a known length) |
| `attempt_started` | Empty payload |
| `entry_started` | Empty payload; entry index and speaker are in the envelope |
| `request_started` | `request_type` |
| `request_completed` | `request_type`, `success`, `elapsed_seconds`, and `error_type` on an exception |
| `system_output` | Available `moves`, `utterance`, and `expected_passivity`, before assertions |
| `transcript_delta` | Newly available `text`, including its newline |
| `entry_completed` | `success`, `status`, `elapsed_seconds`, and safe failure diagnostics when applicable |
| `attempt_completed` | `status`, `result`, `raised`, and `error_type` when applicable |
| `test_completed` | `status`, aggregate `result`, `raised`, and `error_type` when applicable |

Request types are `start_session`, `semantic_input`, `speech_input`, `passivity`,
`service_query`, `service_validation`, `service_action`, `query_results`,
`validation_results`, and `action_results`. Request success means the observed
operation returned without raising, not that the interaction assertion passed.

Completion status is `passed`, `failed` for a failed expectation, or `error` for
an execution exception. `raised=True` means the exception will propagate to the
caller, preserving legacy behavior. Exceptions already handled by the tester
still return the existing failure result and have `raised=False`.

Every repetition has its own attempt events. Only `test_completed` reports the
aggregate outcome, including missing required outcomes. Concatenating transcript
deltas reconstructs the event-visible aggregate transcript, including separators
between repetitions. The legacy repeat result's timing fields still describe the
last executed repetition; attempt events expose each repetition's timings.

Callbacks run synchronously on the test's executing thread. Keep them short
(for example, enqueue events for a transport worker). Ordinary callback
exceptions are logged using only their type and do not fail the test; subsequent
events are still attempted. A callback receives a deep copy and cannot mutate
the tester's response through it. Callback delivery time is excluded from test,
turn, entry, and request durations. A failed observer can miss events; this is
not a durable delivery or replay mechanism. Use separate tester instances for
concurrent executions.

### Diagnostics and compatibility

The existing returned result and buffered transcript are unchanged. Completion
event results contain the existing standard result fields, but use the
event-visible transcript and sanitized failure diagnostics. Raw session/context
objects, offers, service parameters, request URLs, backend response dumps, and
exception messages/tracebacks are not copied into progress events. Missing-output
errors also omit raw response dumps. Speech, semantic moves, and scripted
expectations remain visible and can contain application data; consumers must
apply their own access controls and retention policy.
