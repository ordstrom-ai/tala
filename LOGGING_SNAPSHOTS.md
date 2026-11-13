# Diagnostic snapshot admission and transcript safety

Normal logging keeps original permitted fields when oversized data cannot be
archived. It prioritizes identity/status metadata, but that fallback can still
exceed Azure limits. A failed or denied capture is not a retrieval guarantee.

## Two separate prerequisites

`set_log_snapshot_writer(writer)` configures storage, not permission to collect
data. `set_log_snapshot_policy(policy)` separately configures reviewed admission.
Neither is installed by default. A renderer can also receive `snapshot_writer`
and `snapshot_policy` explicitly.

The policy implements `permits_snapshot(event)` and must return exactly `True`
to approve a complete, already-redacted diagnostic event. It receives a detached
JSON representation. Mutating that copy cannot change the caller's event or the
stored representation: this interface admits or rejects, not sanitizes.

An application-specific policy must reject unapproved content, credentials, and
transcript data in its actual schemas, including arbitrary payload fields and
object representations. Agree permitted events/content, retention, deletion,
and reader access before configuring a real policy. The permissive policies in
tests approve synthetic fixtures only and must not be used by applications.

Tala's existing session-field redactions still run first. Do not bypass them.
The generic guard also rejects recognized utterance/hypothesis/correction,
conversation-message, and SSE-fragment representations anywhere in the JSON.
That guard is deliberately conservative and **not** a general PII detector or
approval for sensitive values under unknown field names. The schema-aware
admission policy is therefore mandatory even with this guard.

## Transcript text is not diagnostic overflow

A diagnostic snapshot acknowledgement is not proof that an utterance was stored
in the restricted transcript ledger or can be retrieved by an authorized viewer.
Recognized transcript-bearing events are not written to diagnostic snapshots.
Their original standard-log fields are retained even when a strict renderer was
requested. Until specialized archival and protected retrieval are validated, a
large transcript event may remain over budget with an explicit unavailable
status. Processing continues; missing content must be presented as a gap.

This release does not remove transcript text, approve new personal-data capture,
enable storage, or provide the pending protected transcript viewer/search.

## Outcomes

| `log_snapshot_state` | Meaning |
| --- | --- |
| `stored` | An explicitly admitted diagnostic event was acknowledged by the writer. |
| `not_configured` | No writer is configured; original fields remain in normal logs. |
| `not_permitted` | Policy is missing/rejecting/failing, or recognized transcript content is present. |
| `failed` | An admitted write failed; normal logs retain the original fields. |

`log_snapshot_reason` distinguishes admission/transcript rejection. Policy/write
failures expose only the exception class, not potentially sensitive error text.
An ID with any state other than `stored` is not a usable snapshot reference.
Strict unavailable summaries are opt-in for non-transcript events only.

## Caller metadata collisions

On an oversized event, top-level snapshot metadata belongs to the renderer.
Caller values using those same names are preserved under `log_original_fields`,
including caller-supplied counters, reasons, and errors. If the caller already
provided `log_original_fields`, its value is retained as
`log_original_fields.log_original_fields`; it is not discarded or mutated.
Other caller fields remain in place, and small records remain unchanged.

The stored snapshot is always the original sanitized event, before renderer
metadata or this collision wrapper is added. A bulky collision wrapper can be
replaced with a snapshot marker only after approved storage succeeds (or by
explicit strict unavailable rendering for non-transcript events). Normal
unavailable/failed logging preserves the original values in full. Readers must
distinguish generated top-level metadata from caller metadata in the wrapper.

## Context and initialization

`FuncBase` preserves an existing bound root correlation ID unless a valid incoming
root header explicitly replaces it. The payload's local request ID remains
separate; it initializes the root only when no root is known. Parent logger
context is not mutated when creating a request logger.

Logging configuration uses a reentrant lock around process-wide setup and
root/file/access handler check-and-add operations. Concurrent setup does not add
duplicate handlers or close existing host handlers. The lock is not held during
ordinary logging, admission checks, or snapshot writes.

`BlobLogSnapshotStore` is an immutable-write/read storage adapter with an injected
private container client and validated UUID/prefix paths. It performs no content
admission or redaction itself. Its client must enforce bounded network
timeouts/retries and use approved identities/permissions. No resource, role,
container, credentials, SAS URL, service wiring, or live Azure proof is supplied
by this code. Authorized durability/retrieval and integrity checks remain release
and rollout gates for actual capture.
