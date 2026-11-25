# Change Log
This changelog is curated and focuses on major changes. For the full historical
record before 12.0.0, see CHANGELOG.legacy.md.

## Unreleased
- Interaction testing: add `IncrementalTDMClient` and the
  `incremental_speech_content` test-case entry for scripted hypothesis updates,
  utterance finalization, and acknowledgement timing before the normal TDM turn.
  The entry is a sequence of hypothesis lists; all but the final list are sent
  as updates, then the last is finalized before the ordinary speech-input turn.
  These scripts must explicitly set the test-case option `incremental_input: true`.
  `TDMClient.start_session(..., incremental_input=True)` sends the matching
  startup opt-in; ordinary session starts retain their original wire payload.
- DDD: add perform-goal replacement and completion-only follow-up hooks. TDM
  runtime support is required before DDDs can use these constructs.

## [31.14.0] - 2026-11-24
- DDD: add perform-goal replacement (`replace_goal`) and completion-only
  follow-up (`on_completion`) hooks. DME runtime support is required before
  DDDs can use these constructs.

## [31.13.0] - 2026-11-23
- DDD: add `forget_instructional_plan` with an explicit child-plan reset scope.
  DME support is required for generated DDDs that use this operation.

## [31.12.0] - 2026-11-23
- SSE/MQTT diagnostics: include the UTC timestamp of the first nonempty response
  content send attempt in the text-free send summary; it marks local send
  initiation, not broker receipt or playback.

## [31.11.0] - 2026-11-23
- SSE/MQTT diagnostics: expose `StreamerQueue.response_send_summary`, a
  text-free summary of content role, transport, stream ID, first response-send
  state, nonempty chunks whose local send call returned, and exception types.
  Returned local calls do not confirm broker receipt or playback.

## [31.10.0] - 2026-11-22
- SSE/MQTT diagnostics: log a text-free, correlated event immediately before the
  first nonempty response-content send attempt. Emit it only when the request-
  scoped stream logger explicitly identifies the stream as a response; filler
  and unclassified streams remain unlabelled. Log synchronous first-send
  failures by exception type and re-raise the original error. Consumer payloads,
  chunking, and buffering settings are unchanged; send initiation is not receipt
  or playback confirmation.

## [31.9.0] - 2026-11-19
- GPT budgets: share attempt counters across related local calls and forwarded
  workflows, preserve the budget's priority, and allow explicit corrections of
  completed requests without restarting their allowance.
- Budgeted streaming: preserve finish reasons through trailing usage events and
  reject truncated, filtered, or unfinished completions even after text arrives.
- Budgeted streaming: add the optional `on_usage` observer to retain received usage
  independently of text and completion validity, enabling accounting of failed
  attempts without duplicate reports.
- GPT retries: retain the failed attempt's context when concurrent work exhausts
  the retry allowance or its deadline expires before reservation.

## [31.8.0] - 2026-11-17
- DDD: support the XML `findout` `force` Boolean shorthand to forget existing
  predicate values before asking a predicate-backed wh or yes/no question. This
  requires the DME plan-order-aware `RemoveFindout` behavior before use.

## [31.7.0] - 2026-11-17
- Interaction testing: configure the SSE stream read-idle timeout with
  `SSE_STREAM_READ_TIMEOUT_SECONDS` (default: 10 seconds); derive the startup
  wait from it while leaving the separate stream-completion timeout unchanged.
- DDD: interpret `allow_answer_from_pcom` using XML Schema boolean values
  (`true`/`1` and `false`/`0`); an absent attribute remains false.
- Documentation: update the README and package metadata to point to the
  Engineering Reference documentation.

## [31.6.0] - 2026-11-17
- Requestor: add opt-in priority/workload budgets with distinct assignment,
  first-generated-text, completion, and total deadlines; bounded attempts; and
  phase-aware timing/failure metadata. No numerical live budgets are enabled.
- Retry safety: do not blindly resubmit Requestor POSTs after read timeouts or
  connection failures with an unknown outcome; retain retries for safe
  pre-send connection timeouts. Signal completion for failed deployment-assignment
  workers so callers cannot wait forever.
- Streaming: add cancellable asynchronous model-stream consumption that ignores
  empty protocol messages when measuring time to first generated text and closes
  timed-out streams, discarding late local output.

## [31.5.2] - 2026-11-14
- Interaction testing: stop waiting for streamed speech when a silent response
  has no speech expectation. Speech-asserting turns still require completed SSE
  output and use streamed text.

## [31.5.1] - 2026-11-14
- Interaction testing: wait up to 10 seconds for streamed output to finish;
  report connection, stream, and completion timeouts instead of returning
  partial or empty speech, and close the listener after failures.

## [31.5.0] - 2026-11-13
- Logging: preserve existing host/exporter handlers and make root, file, and
  access-handler initialization safe under concurrent setup.
- Diagnostics: add optional oversized-event snapshots with explicit capture
  admission. Replace bulky fields with references only after approved storage
  succeeds; preserve conflicting caller metadata in `log_original_fields`.
- Safety: retain existing redactions and keep recognized transcript content out
  of diagnostic snapshots. Missing, rejected, or failed capture retains original
  fields with an explicit status; that fallback can still exceed telemetry limits.
  No production capture policy or storage wiring is enabled by this release.
- Correlation: accept and propagate bounded, text-free HTTP identifiers while
  keeping inherited root correlation separate from local request IDs.
- SSE: add optional stream handles and copied producer correlation metadata.
  Isolate overlapping producer state and connection/startup/send failures while
  preserving consumer event/data/text, MQTT messages, and 31.4.0 pronunciation
  replacement/pass-through behavior. Legacy session-ID calls remain supported.
- CI: require dependency freshness on PR submissions, not again on resulting
  `main` commits. Application tests, lint, and artifact checks still run on both.

## [31.4.0] - 2026-11-13
- SSE/MQTT streaming: add `PRONUNCIATION_REPLACEMENTS_ENABLED` to disable
  text substitutions used to guide TTS pronunciation, along with their
  word-boundary buffering. The setting defaults to enabled; empty replacement
  models use ordered pass-through automatically.

## [31.3.0] - 2026-11-12
- DDD: allow `forget` and `forget_shared` to target `action_status` propositions.

## [31.2.3] - 2026-11-11
- Interaction testing: refresh session state after query, action, and
  validation result continuations so subsequent turns use the latest service
  result.

## [31.2.1] - 2026-11-10
- SSE streaming: skip empty or missing persona and voice settings instead of
  resetting the frontend defaults. Nonempty settings, content, completion events,
  and MQTT behavior are unchanged.
- Dependencies: update Azure Data Tables to 12.7.0 and Paho MQTT to 2.2.0.

## [31.2.2] - 2026-11-10
- Documentation: correct the changelog to record the published Tala 31.2.1
  release under its version and publication date.

## [31.2.0] - 2026-11-07
- Interaction testing: add optional, structured progress callbacks for test,
  repetition, entry, request, transcript, and system-output events. Existing
  result dictionaries, transcripts, and exception behavior are preserved;
  callback diagnostics omit raw backend payloads and exception details.

## [31.1.3] - 2026-11-05
- Serialization: preserve domain context in `Findout` and `Raise` resource IDs
  so plans asking the same domain-independent question do not overwrite each
  other during JSON:API round-trips. This prevents incorrect domain restoration
  and the resulting `KeyError: 'CoverDomain'` in affected surgical dialogues.
  The question's own identity and domain-independent semantics are unchanged.
- Compatibility: existing resource IDs remain readable. Previously corrupted
  session state cannot be repaired automatically; affected sessions should be
  restarted after consumers upgrade to this version.
- Packaging: advertise and test Python 3.12 as the supported platform version.

## [31.1.2] - 2026-10-30
- Documentation: clarify Tala’s role, capabilities, installation, and service
  prerequisites; add a Requestor client guide and update repository metadata.

## [31.1.0] - 2026-10-28
- Requestor: forward strict JSON Schema response formats, expose completion
  outcomes, and include output schemas in cache identity.
- Requestor: raise `GPTStructuredOutputError` for malformed structured JSON
  instead of silently returning a default response.

## [31.0.2] - 2026-10-21
- DDD XML: ignore formatting whitespace in `forget` and `forget_shared`
  proposition children. This fixes a compilation failure with normally
  indented XML; comments around the proposition child are also supported.

## [31.0.1] - 2026-10-20
- DDD JSON: validate definition schemas and fixtures; correct KPQ, condition,
  forget, and bundle schema definitions.

## [31.0.0] - 2026-10-19
- CLI: remove the deprecated multi-command `tala` interface; use
  `tala-interact` as the supported interaction command.
- DDD JSON: add loading for bundled and separate component definitions, with
  named component formats.
- DDD language: add boolean and belief/commitment membership conditions, and
  remove implicit service-action downdating in favor of explicit conditions.
- DDD loading: add active-DDD validation, require non-empty DDD name lists, and
  harden numeric coercion.
- Serialization: expand JSON:API support for dialogue events, moves, plans, and
  iterator state; tighten serialization and deserialization.
- Orchestration: preserve the configured `AUTO` TIS log format and reduce
  duplicated payload data.
- Streaming: add connection timeouts and handle client setup failures without
  leaving streamer workers blocked; run worker threads as daemons.
- Configuration: update the default GPT model to `gpt-4o-2024-11-20` and let
  test logging use `LOG_LEVEL` when no explicit level is provided.

## [30.0.1] - 2026-05-08
- JSON parsing: restore support for legacy `service_action` plan items and
  service-result propositions.

## Highlights since 12.0.0 (major changes only)

### 29.x-31.x (2026)
- Requestor improvements: caching, timeouts, reasoning effort, content-filter
  handling, JSON repair retry, and improved logging.
- JSON:API hardening, DDD JSON/XML parity, and JSON bundle loading.
- Deprecated APIs and semantic logic removed; move module refactors and legacy
  parsing fixes.

### 27.x-28.x (2025)
- NLG refactor and move to `tala.nlg`.
- User rates DB extended with dialogue IDs and author notification parameters.

### 25.x-26.x (2025)
- New JSON serialization format for DDD-related models; `<once>` plan item
  introduced.
- SSE client supports multiple sessions; NLG enhancements for move sequences
  and slots.

### 23.x-24.x (2025)
- Packaging moved to `pyproject.toml`.
- Updated SSE streamer endpoint configuration.

### 21.x-22.x (2025)
- Streaming test coverage and MQTT streaming fixes; stream checking added then
  removed for performance.
- NLG added to Tala and expanded; lightweight SSE client introduced.

### 19.x-20.x (2024)
- Interaction testing overhaul: new framework layout and endurance testing
  removed.
- MQTT client updates including pronunciation lexicons and timing constraints.

### 17.x-18.x (2024)
- Quota DB tooling: table handler, user rates tracking, and author/offer quota
  updates.
- Python 3.11 support and publish action updates.

### 15.x-16.x (2023-2024)
- New JSON-based interaction tests and fixes for interpretation output.
- TDM-specific functionality moved out of Tala; model class renames and HTTP
  formatting simplification.
- Interaction tester improvements: device id, neural parameter, and logging
  defaults.

### 14.x (2023)
- Migration to GitHub with PyPI publish workflow.
- Deprecation of non-pythonic names and migration toward properties.
- Interaction test generation updated for TDM start behavior changes.

### 12.x-13.x (2022-2023, from legacy tags)
- JSON support for DDDs and ODBs: JSON parsing, ODB serialization to JSON, and
  on-demand JSON DDD loading.
- TIS sessions and payloads stored as JSON (multiple betas in 13.2.x).
- Configurable HTTP service timeout and removal of the libmagic dependency.
