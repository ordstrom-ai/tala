# Releasing Tala

This checklist describes how to release the existing `tala` package to PyPI.
The GitHub Release is the explicit authorization to publish; publishing it
starts `.github/workflows/python-publish.yml` automatically. Do not publish
from a local machine or create a release as part of ordinary PR work.

## Prepare a release

1. Choose the next release version by checking the latest version on PyPI and
   following the project's existing versioning convention. For example, an
   additive API release can advance `31.1.3` to `31.2.0`. Keep the GitHub tag
   in the form `X.Y.Z` or `vX.Y.Z`; the publish workflow accepts either.
2. Review all changes since the previous release, not just the most recent PR.
   Confirm the `Unreleased` section in `CHANGELOG.md` accurately describes the
   user-visible changes and any compatibility considerations.
3. Before making a GitHub Release, move the release notes from `Unreleased` to
   a dated `X.Y.Z` changelog heading in a reviewed PR. Leave a fresh, empty
   `Unreleased` section at the top. Merge the PR to `main`.
4. Wait for the required `tests` Actions check to pass on the resulting `main`
   commit. Record that exact commit SHA; do not make further commits before
   creating the release for it.

Tala's package version is derived from Git tags with `setuptools-scm`; do not
manually change the package version in `pyproject.toml` for a release.

## Publish

1. Open the repository's **Releases** page and create a new release using the
   exact tested `main` commit from the preparation step. Create the selected
   `X.Y.Z` (or `vX.Y.Z`) tag at that commit.
2. Use a clear title such as `Tala X.Y.Z` and add concise release notes based
   on the dated changelog section. Review the tag, target commit, version, and
   notes before publishing.
3. Publish the GitHub Release. Publishing—not saving a draft—triggers the
   PyPI workflow. The `pypi` environment currently has no required-reviewer
   protection, so the workflow can start publishing immediately.
4. In Actions, verify that the **Publish Tala to PyPI** run succeeds for the
   release tag. It checks that the exact tag commit passed the required `main`
   tests, builds a wheel and source distribution, verifies their versions, and
   publishes them using PyPI Trusted Publishing.
5. Verify that the new version appears on PyPI. In a clean Python 3.12
   environment, install `tala==X.Y.Z` and smoke-test importing the package and
   the released feature. Do not replace the shared development environment's
   dependencies to perform this check.

## If publishing fails

- Read the failed Actions step and confirm whether PyPI already received the
  artifacts before attempting a retry. Rerun the publishing workflow only when
  appropriate; PyPI does not allow replacing an already published version.
- Never move or reuse a published version tag to replace its artifacts. If the
  released package needs a correction, prepare and publish a new version after
  its own `main` tests pass.
- Report the failed release and its tag, commit SHA, workflow run, and PyPI
  publication status. Do not commit or expose PyPI credentials.

## Automation

The existing release-triggered workflow already validates the tagged commit,
builds and checks the distribution files, and publishes to PyPI. A separate
release-preparation Action is not needed for the current release cadence. If
preparation becomes repetitive, consider a manual, non-publishing validation
workflow that checks a proposed version and commit and produces a release
checklist. It must not create tags or publish a GitHub Release automatically.
