# Continuous integration

VEGA uses `.github/workflows/ci.yml` as a secret-free, least-privilege release
baseline. It runs for pull requests and pushes to `main`.

## Matrix

The full suite and compileall run on Windows and Linux with Python 3.12, 3.13,
and 3.14. These versions make the README's Python 3.12+ support statement
explicit and testable. A single Ubuntu/Python 3.12 release-gate job runs the
focused critical tests, identity, production policy consistency, smoke test,
repository hygiene, and the built-in Release Manager. Release Manager includes
its own full-suite check, so it is not duplicated in every matrix cell.

For v2.13 the focused set includes controlled lifecycle, confirmation binding,
workflow persistence/security, recovery, exact CLI routing, portable path
safety, execution traces, runtime diagnostics, v2.12 state integrity, and
release identity. The full matrix remains the compatibility authority.

Pytest uses `-rs`, so platform-conditional skips and their reasons are visible in
every job. Windows symlink tests may skip when the runner lacks symlink
privileges; other failures are not suppressed.

## Security

Workflow permissions are `contents: read`. Checkout credentials are not
persisted. CI uses no repository secrets, Ollama service, external model,
network service, commit, merge, tag, or release permission. The workflow cannot
publish VEGA.

`actions/checkout` and `actions/setup-python` are pinned to immutable official
commit SHAs. To update them, resolve the intended official major tag through the
GitHub API, review the upstream release notes and diff, replace the SHA and the
adjacent major-version comment together, and validate the full matrix in a pull
request.

## Repository hygiene

`scripts/check_repository_hygiene.py` checks working, staged, and committed-range
whitespace; rejects tracked generated runtime state; and verifies representative
ignore rules. The same command is available to the built-in Release Manager.
