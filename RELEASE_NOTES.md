# VEGA v2.13.0 Release Notes

VEGA v2.13.0 ships **Controlled Coding Workflows** on top of the stabilized
v2.12.1 local-state baseline.

## What is new

* Deterministic `bug-fix`, `feature`, `refactor`, allowlisted `test`, and
  read-only staged/unstaged `review` workflows.
* Separate single-use patch and test approvals bound to the exact workflow,
  stage, patch identity, workspace revision, test group, command, and state.
* Frozen slotted schema-v2 workflow state, manual allowlisted serialization,
  atomic locked persistence, checkpoints, state-only recovery, and conservative
  restart reconciliation.
* A maximum of three separately confirmed test-fix iterations with failed-test
  evidence and rollback availability preserved.
* Payload-free workflow decisions in optional execution traces and read-only
  doctor diagnostics.
* Portable Windows/POSIX path enforcement and protected Git, state, cache,
  virtual-environment, and `node_modules` targets.

## Security and compatibility

The model receives no direct tools or confirmation authority. Ordinary language
and model output cannot approve dangerous stages. Raw tasks, prompts, diffs,
contents, test output, stdout/stderr, arguments/results, exceptions, absolute
paths, environment data, confirmation material, and secrets are excluded from
workflow state and observability.

Ordinary chat, manual Patch/Test commands, public traces, v2.10/v2.11 trace
records, v2.12 diagnostics/repair, release tooling, and safely migratable old
workflow state remain supported. Ambiguous old state fails closed.

## Validation and CI

The release requires focused workflow/security tests, the full suite,
compileall, release identity, production policy consistency, smoke, built-in
Release Manager, whitespace, and generated-state hygiene. CI runs Windows and
Linux on Python 3.12, 3.13, and 3.14 without secrets or publication authority.

Full architecture, transition, threat-model, migration, validation, and known
limitation details are in
[`docs/v2.13-architecture.md`](docs/v2.13-architecture.md) and
[`docs/releases/v2.13.0.md`](docs/releases/v2.13.0.md).

Local Windows/Python 3.12 results: `233 passed, 4 skipped, 21 subtests` focused;
`1017 passed, 7 skipped, 136 subtests` full. The skips are explicit unavailable
symlink privileges (five pre-existing and two new path-safety cases).
