# VEGA Coding Workflows

VEGA v2.2.0 provides durable `feature`, `bugfix`, and `refactor` runs. Each run
collects real project context and builds a plan before entering `waiting_patch`.
No patch is required at start. `/workflow attach-patch` validates a real pending
Patch Tools artifact and advances to `waiting_confirmation` without applying it.
The confirmed patch is then applied, verified once, and recorded.

Statuses are `created`, `analyzing`, `planning`, `waiting_patch`, `waiting_confirmation`,
`executing`, `verifying`, `completed`, `failed`, and `cancelled`. Terminal runs
cannot resume.

Only one JSON file may exist in `data/workflows/active/`. State writes are atomic.
Completed, failed, and cancelled files move to `data/workflows/history/`. Corrupt
JSON is reported and never silently replaced.

Missing patch artifacts and missing Test Tools fail closed. Tests run exactly once; failure is recorded for manual intervention. Refactor
requests are behavior-preserving. Mixed refactor/feature scope must be identified.

Ordinary unambiguous coding text creates only a read-only draft. Ambiguous text
requires the user to choose a type first. Workflow plans are never copied into the
active TaskManager task implicitly; `/workflow link-task <task_id>` is explicit.
