# AGENTS.md

> **Shared dependency freshness:** Before committing a change,
> read `~/dev/AGENTS.md` and follow its mandatory submission-only policy.
> This includes documentation-only changes and overrides older guidance below.
# Guide for agentic coding tools in this repo.

## GitHub review and package-release policy

- The canonical repository is `ordstrom-ai/tala`; use pull requests against
  `main` and descriptive feature branches.
- Use guarded GitHub commit, push, and pull-request workflows. GitHub commits
  are ordinary commits; do not add Gerrit Change-Id footers.
- Require the `tests` Actions check before merging changes to `main`.
- Publish the existing PyPI package `tala` only from an explicitly authorized
  GitHub Release. `.github/workflows/python-publish.yml` uses PyPI Trusted
  Publishing from the `pypi` GitHub Environment and verifies that the release
  tag's exact commit passed the required `main` tests.
- Do not commit or expose PyPI tokens. Do not change the package's existing
  PyPI-facing metadata as part of the GitHub hosting migration.
- GitHub `main` is the canonical Tala source. Treat Gerrit as a read-only
  historical reference; do not submit further Gerrit changes.
- Jenkins is not a Tala CI or release path. Use GitHub Actions for CI and the
  authorized PyPI Trusted Publishing workflow for package releases.
- Follow [RELEASING.md](RELEASING.md) to prepare and publish a package release.

## Environment
- Use the shared Python 3.12 environment at `~/python_312_environment`.
- Activate it before any command:
  - `source ~/python_312_environment/bin/activate`

## Project snapshot
- Package name: `tala` (Python 3.12).
- Tests use `pytest` with class-style tests in `tala/**/test`.
- Lint/format: `flake8` and `yapf` configured in `setup.cfg`.
- Dev tools listed in `requirements-dev.txt`.

## Install / setup
- Install runtime deps:
  - `python -m pip install -e .`
- Install dev deps:
  - `python -m pip install -r requirements-dev.txt`

## Build
- Build sdist/wheel:
  - `python -m build`

## Lint
- Flake8 (configured in `setup.cfg`, 120 col limit):
  - `python -m flake8 tala`
- Pylint (available, no explicit config):
  - `python -m pylint tala`
- Run `flake8` clean before committing anything.
- Run `python -m flake8 tala` before each commit.
- Do not change CI Flake8 excludes to account for editor backup/lock files;
  ignore those locally.

## Format
- YAPF (configured in `setup.cfg`):
  - `python -m yapf -i path/to/file.py`
  - `python -m yapf -ir tala`

## Tests
- Run all tests:
  - `python -m pytest`
- Run tests in a module:
  - `python -m pytest tala/utils/test/test_requestor.py`
- Run a single test case:
  - `python -m pytest tala/utils/test/test_requestor.py::TestGPTRequest::test_basic_call`
- Run by keyword expression:
  - `python -m pytest -k requestor`

## Pytest details
- Config file: `pytest.ini` (excludes `tala/ddds`).
- Tests commonly use class fixtures (`setup_class`) and pytest fixtures.

## Code style guidelines

Follow the shared maintainability and Python conventions in `../AGENTS.md`.

### Imports
- Keep one import per line unless a short `from ... import ...` list is clearer.
- Prefer absolute imports (e.g., `from tala.utils.func import getenv`).

### Formatting
- Max line length: 120.
- YAPF is the formatter; do not reformat with a different tool.
- Keep dicts and lists readable; existing code often expands large literals.
- Avoid trailing whitespace and keep blank lines between top-level defs.

### Logging
- Use structured logging via `structlog` (`tala/utils/func.py`).
- Use `setup_logger(__name__)` and log with context (kwargs).
- Avoid logging large session fields directly; redaction is centralized.

### Public API surface
- `tala/__init__.py` exposes package-level names; keep it stable.
- New modules should live under the relevant subpackage (`ddd`, `model`,
  `utils`, `log`, `service`).

### Tests
- Tests are in `tala/**/test` or `tala/**/test/**.py`.
- Use pytest-style `assert` with clear error messages.
- Prefer small, deterministic tests; patch external calls.

### Data and files
- XML/DDD assets live under `tala/ddd` and are packaged via `pyproject.toml`.
- Avoid touching `tala/ddds` in tests; it is excluded from pytest traversal.

## Repository-specific notes
- No Cursor rules were found in `.cursor/rules/` or `.cursorrules`.
- No Copilot instructions were found in `.github/copilot-instructions.md`.
- Update `CHANGELOG.md` for user-facing changes.

## Commit and GitHub workflow
- Follow `../AGENTS.md` for platform-wide rules and guarded GitHub workflows.

## When in doubt
- Follow nearby code for package-specific behavior, not as an exception to the
  shared standards in `../AGENTS.md`.
