# Tala 31.5.2 release preparation

**Status: prepared, not published.** This patch release covers the silent-turn
stream-listener fix merged in [PR #22](https://github.com/ordstrom-ai/tala/pull/22).
Preparing these notes does not create a tag or authorize publication.

## Prepared GitHub Release title

Tala 31.5.2

## Prepared GitHub Release body

### Interaction testing

When an interaction response has no utterance and the next system expectation
does not assert speech, stop waiting for an SSE completion that will not be
produced. Semantic moves and passivity expectations remain checked. If speech is
expected, continue to require completed SSE and use streamed text; do not fall
back to HTTP response text.

## Finalization checklist

- After this preparation change is merged, inspect the final `main` source and
  confirm the dated changelog covers all changes since Tala 31.5.1.
- Verify required application, build, lint, and artifact checks on the exact
  final `main` commit; record that commit before creating a release.
- Create and publish a GitHub Release for that exact tested commit only with
  separate authorization. The published release triggers PyPI Trusted
  Publishing; verify the workflow and PyPI version afterward.
