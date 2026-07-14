# VEGA v2.12.1 Release Notes

VEGA v2.12.1 stabilizes **Local State Integrity & Recovery** after an independent
audit of the published v2.12.0 release.

## Patch-release decision

A patch release is required. In a clean checkout, the configured pytest
`--basetemp .tmp/...` parent did not exist because `.tmp` was entirely ignored;
the reproduced baseline produced 178 setup errors until the directory was
created. The security review also found material state-integrity edge cases in
quarantine evidence validation, report structure validation, bounded reads,
descriptor cleanup, and failure-code accuracy.

## Correctness and security fixes

* `.tmp/.gitkeep` makes built-in validation reproducible while generated temp
  content remains ignored.
* Lock stream creation closes its raw descriptor on failure. Existing lock probes
  use the same no-follow open path as mutation locks.
* Generated trace/report reads are limited to the configured cap plus one byte,
  including concurrent-growth races.
* Existing content-addressed quarantine evidence must exactly match expected
  content before repair can replace the source.
* Generated reports require a compatible v2.11/v2.12 top-level schema; arbitrary
  JSON objects no longer pass as healthy reports.
* Stale-temp cleanup and quarantine-retention failures use explicit repair and
  quarantine codes instead of a misleading scan-limit code.

## Cross-platform CI

The new secret-free GitHub Actions workflow runs on pull requests and pushes to
`main`. Windows and Linux test Python 3.12, 3.13, and 3.14. The matrix runs
compileall and the full suite; one release-gate job runs focused critical tests,
identity, production policy consistency, smoke, repository hygiene, and the
built-in Release Manager.

Workflow permissions are read-only, checkout credentials are not persisted, and
official actions are pinned to immutable commit SHAs. CI cannot commit, merge,
tag, publish, access Ollama, or use repository secrets. Skip reasons are visible
with `pytest -rs`.

## Compatibility and migration

No migration is required. Valid v2.10/v2.11 traces, v2.11 reports, all valid
v2.12 state, public trace APIs, `/doctor state status`, `/doctor state repair`,
and existing manual commands remain compatible. Invalid generated reports now
fail closed and are quarantined only by explicit repair.

## Validation

The release gate covers a fresh detached worktree, tracing enabled/disabled,
legacy and rotated traces, multiprocessing, report interruption, torn and
complete corruption, quarantine retention/substitution, contention, cleanup,
Windows/POSIX adapters, compileall, identity, production policy, smoke, Release
Manager, whitespace, Git hygiene, and the full Windows/Linux Python matrix.

Local Windows/Python 3.12 validation recorded `117 passed, 2 skipped` for the
focused stabilization/release set and `996 passed, 5 skipped, 133 subtests` for
the complete suite. Compileall, identity, policy consistency, smoke, whitespace,
and generated-state hygiene passed. The five skips are explicit symlink tests on
an account without symlink privileges; four predate v2.12.1 and the v2.12 state
lock test uses the same platform condition. The two collection warnings predate
v2.12.1 and concern helper classes with constructors.

Windows/Linux Python-matrix results and CI job links are recorded in the pull
request and published GitHub Release after all jobs complete.

## Known limitations

* Locks coordinate cooperating VEGA processes and remain advisory.
* Recovery is bounded and fail-closed rather than forensic.
* Windows symlink tests conditionally skip without symlink privileges.
* No startup repair, background monitor, telemetry, autonomous execution, model
  tool authority, or in-product publication is provided.
