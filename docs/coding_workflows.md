# VEGA Controlled Coding Workflows

VEGA v2.13.0 provides deterministic, persisted workflows without giving the
model direct tool authority. Only one workflow may be active.

## Commands

```text
/workflow types
/workflow list
/workflow start bug-fix <task>
/workflow start feature <task>
/workflow start refactor <task>
/workflow start test <allowlisted-group>
/workflow start review <unstaged|staged>
/workflow attach-patch <pending_patch_id> [test-group]
/workflow approve patch <workflow_id>
/workflow approve tests <workflow_id>
/workflow status [workflow_id]
/workflow show <workflow_id>
/workflow resume [workflow_id]
/workflow cancel [workflow_id]
/workflow rollback <workflow_id>
/workflow history
/workflow review
```

Commands and approval keywords are case-sensitive. Unknown, fuzzy, malformed,
or extra-argument forms show usage and do not execute an action. Text that does
not begin as a command, including model output containing a command example,
cannot confirm a workflow.

## Coding flow

A coding workflow investigates the project read-only and enters
`waiting_patch`. Attach a real pending Patch Tools ID; this records an exact
confirmation binding but does not modify the target. Patch approval rechecks
the managed patch identity and workspace revision, consults permission policy,
and applies it once. It then creates a different binding for the configured
test group. Test approval runs only that group once.

Failure preserves the applied patch, bounded test outcome, investigation,
rollback availability, and safe next actions. A new patch and test cycle needs
new approvals. The compiled limit is three iterations.

## Test and review

`/workflow start test workflow` gates the focused v2.13 workflow group.
`/workflow start test all` is a separate full-suite request and confirmation.
No arbitrary arguments or shell commands are accepted.

Review accepts only `unstaged` or `staged`, reads bounded Git diff evidence, and
returns structured fixed-code findings. It never applies a patch.

## Resume, cancellation, and rollback

Resume never replays tests. If a process stopped after Patch Tools completed an
apply but before workflow state advanced, resume reconciles the already-applied
managed patch and waits for test approval. Interrupted `tests_running` becomes a
safe failure.

Cancellation is legal at controlled waiting stages and does not silently roll
back. Rollback is explicit, single-use, and available only while the complete
workspace still matches the post-patch revision. Otherwise it returns the fixed
`rollback_refused` code.

## State and migration

State lives in the existing `data/workflows/active` and `history` directories,
uses the v2.12 generated-state lock, atomic replacement, and checkpoints, and
contains only bounded allowlisted metadata. Raw task, diff, file content, test
output, arguments/results, exception text, paths, tokens, and secrets are not
stored.

Compatible v1 `waiting_patch` state is sanitized into schema v2. Ambiguous old
executing or confirmation stages fail closed and cannot advance. See
[`v2.13-architecture.md`](v2.13-architecture.md) for the complete transition and
threat model.
