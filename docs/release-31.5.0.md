# Tala 31.5.0 release record

**Status: published on 2026-11-13.** Version 31.5.0 is available on
[PyPI](https://pypi.org/project/tala/31.5.0/). The publishing workflow succeeded
for source commit `3273f708a0112e3607b5effb12558344086061a3`:
[publish run](https://github.com/ordstrom-ai/tala/actions/runs/43452974020).

The runtime changes came from [PR #18](https://github.com/ordstrom-ai/tala/pull/18)
and preparation from [PR #19](https://github.com/ordstrom-ai/tala/pull/19). The
release body below is the prepared wording, not a claim that it exactly matches
the published GitHub description. Post-publication repository documentation
corrections do not change the released tag, source commit, or PyPI artifacts.

## Prepared GitHub Release title

Tala 31.5.0

## Prepared GitHub Release body

### Logging and diagnostic snapshots

- Preserve existing host/exporter handlers and prevent duplicate handlers during
  concurrent initialization.
- Add optional size-aware diagnostic snapshots with explicit capture admission,
  retrievable references after storage acknowledgement, and honest unavailable
  or failed-capture states.
- Preserve caller snapshot-metadata collisions in `log_original_fields` without
  changing the original sanitized snapshot.

### Request and stream correlation

- Propagate bounded, text-free HTTP context while keeping root correlation IDs
  separate from local request IDs.
- Add optional SSE stream handles and copied producer metadata so overlapping
  producers keep their own context. Legacy session-ID calls, consumer-facing
  event/data/text, MQTT messages, and 31.4.0 pronunciation behavior remain
  compatible.
- Clean up failed connections/thread startup and report send failures using the
  failing stream's own output and original cause.

### Safety and limitations

Snapshot storage and its admission policy are not enabled by default. Configuring
a writer alone does not authorize capture. Existing redactions remain, and
recognized transcript content stays out of diagnostic snapshots and retains its
standard-log fallback. Unarchived fallback can still exceed Azure's limits;
capture failure is not a complete audit or retrieval guarantee.

This library release does not provision storage, change identities or settings,
enable production capture, or establish Azure-native tracing or authorized
transcript retrieval. Service adoption requires published-version pins and
installed-package validation. See `LOGGING_SNAPSHOTS.md` for the detailed contract
included with the logging changes.

### Submission checks

Dependency freshness remains required for each PR submission. It is not repeated
on the resulting `main` commit; application tests, lint, package build, and
artifact smoke checks still run on both PRs and `main`.

## Finalization checklist used for preparation

This historical checklist is not an instruction to publish 31.5.0 again. Future
releases must follow `RELEASING.md` and inspect their own final merged source.

- Merge #18 and this preparation PR in the intended order; reconcile the dated
  changelog with the actual included code and leave a fresh `Unreleased` section.
- Confirm 31.5.0 is still the intended unused version and update the release date
  if publication is delayed.
- Verify the required application/build/lint checks for the exact final `main`
  SHA. Do not substitute the current preparation branch's tests for that result
  or rerun submission-only freshness during release.
- Record that final SHA at publication time; none is selected in this document.
  Versions come from Git tags via `setuptools-scm`, not a manual `pyproject.toml`
  version edit.
- Obtain separate publication authorization and use the approved GitHub
  Release/PyPI Trusted Publishing workflow. Creating these notes does not create
  a tag, draft GitHub Release, or publication.
- Verify publishing succeeds, confirm `tala==31.5.0` on PyPI, and smoke-test the
  released APIs in a clean Python 3.12 environment without replacing shared pins.
- Keep Azure capture, raw-utterance removal, and deployments behind their
  separately approved durability, access, privacy, and release gates.
