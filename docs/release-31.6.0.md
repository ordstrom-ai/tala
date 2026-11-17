# Tala 31.6.0 release preparation

**Status: prepared, not published.** This release covers the phase-aware GPT
retry/budget API merged in [PR #24](https://github.com/ordstrom-ai/tala/pull/24)
at main commit `79f46495e388c98e83d25f556ba49a1396883670`. PyPI 31.5.2 was the
latest published Tala version when these notes were prepared. Preparing these
notes does not create a tag or authorize publication.

## Prepared GitHub Release title

Tala 31.6.0

## Prepared GitHub Release body

### Phase-aware GPT budgets and retry safety

Add opt-in workload- and priority-specific budgets for deployment assignment,
first generated streaming text, completed non-streaming responses, and a total
request deadline. Calls within one request share a bounded attempt allowance;
failures report their phase, timings, deployment, request ID, and attempt ID.
No numerical runtime profiles are enabled by default.

Do not resubmit Requestor POSTs after a read timeout or connection failure whose
outcome is unknown. Retry safe pre-send connection timeouts, and keep budget-aware
retries with the caller. Stream cancellation closes the local request and ignores
late local output; it cannot guarantee that provider-side generation or billing
stops. This does not authorize resetting an answer after text has been forwarded.

## Finalization checklist

- After this preparation PR is merged, inspect the final `main` source and confirm
  the dated changelog covers all Tala changes since 31.5.2 and `Unreleased` is
  empty.
- Require the `tests` Actions check to pass on that exact final `main` commit;
  record its SHA before creating a release. No further commits should intervene.
- Create and publish a GitHub Release only for that exact tested commit, with
  separate release authorization. The published release triggers PyPI Trusted
  Publishing; verify the workflow and PyPI version afterward.
- Release-dependent Requestor and client PRs can be submitted for review before
  publication, but should not enable the budget profiles until the released Tala
  package and budget-aware Requestor are available.
