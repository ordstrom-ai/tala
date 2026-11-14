# Change Log
This changelog is curated and focuses on major changes. For the full historical
record before 12.0.0, see CHANGELOG.legacy.md.

## Unreleased
- Interaction testing: wait up to 10 seconds for streamed output to finish;
  report connection, stream, and completion timeouts instead of returning
  partial or empty speech, and close the listener after failures.
- Logging: preserve caller snapshot-metadata collisions in `log_original_fields`,
  retain inherited root correlation unless explicitly replaced by an incoming
  root header, and serialize handler initialization across threads.
- Logging: preserve preconfigured root handlers without closing them. An optional
  snapshot writer, explicit capture-admission policy, and `BlobLogSnapshotStore`
  archive approved oversized diagnostic events; only the
  largest fields are replaced to fit the 6 KiB summary budget after storage succeeds.
  Without storage, or when it fails, normal logging preserves the original fields
  with explicit archive status; Azure's existing size limits can still truncate that fallback.
- Logging: a writer alone does not authorize capture. Missing/rejecting/failing
  policies report `not_permitted`. Recognized transcript fields are never copied
  to diagnostic snapshots or removed from their standard-log fallback, including
  in strict rendering mode. No production capture policy is installed.
- Logging: bind available request, offer, and turn IDs in `FuncBase` log context
  so utterance archive records can be joined to service logs.
- Logging: propagate bounded, text-free HTTP correlation headers and accept them
  in `FuncBase`. Preserve root correlation IDs separately from local GPT-call IDs.
- SSE: add optional per-stream handles and copied correlation metadata for
  producer envelopes. Overlapping streams keep separate context; legacy SSE
  event/data and MQTT messages remain unchanged.
- SSE: publish a session only after connection and joiner startup succeed, so
  overlapping failures cannot restore unusable sessions or replace newer streams.
  Send failures report the failing stream's own output and preserve their cause.

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
