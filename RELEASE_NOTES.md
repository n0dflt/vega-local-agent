# VEGA v3.0.0 Release Notes

VEGA v3.0.0 introduces the **Operator Console and Live Execution UX** on top of
the v2.13.0 controlled-workflow and state-integrity baseline.

## What is new

* A compact, width-aware startup screen showing the canonical version, current
  workspace, selected model, and runtime readiness.
* Restrained ANSI color, safe no-color output, Unicode symbols, and complete
  ASCII fallbacks for Windows and redirected terminals.
* One compact `vega ›` input prompt without a second input loop.
* Immutable, request-local progress events for analysis, planning, validated
  plan display, real step counts, confirmation waits, skipped/failed steps, and
  terminal outcomes.
* Fail-soft TTY and sequential renderers that cannot execute or retry tools.
* A request-local live timer with correct hour/minute/second formatting and
  terminal handling for success, failure, cancellation, and timeout.
* Exact Ollama input, output, and total token usage when supplied by the server;
  streaming reads usage only from the final `done` chunk and missing usage is
  never estimated.
* Structured `REQUEST_METRICS` session-log records with timing, status, phase
  durations, and nullable usage counts, without additional sensitive content.

## Breaking changes

The terminal presentation is intentionally different. The framed ASCII logo,
`VEGA SESSION` block, startup Internet/network/safety/log details, decorative
slogan, and the old two-line model prompt are gone. Automation that parses or
snapshots those exact strings must be updated.

There are no command, permission, plugin, workflow, stored-state, diagnostic,
or tool-execution schema changes. The pre-v3 Python call shapes for
`render_startup_screen(...)` and `VegaStatus(model, internet, version)` remain
accepted; removed visual fields are ignored.

The unused internal `core.agent_runtime.banner()` and `fallback_banner()`
helpers and direct execution of `scripts/vega_banner.py` are removed. Launch
VEGA through `scripts/vega.py`/the supplied wrappers; Python presentation code
can import `scripts.vega_banner.render_banner()` or `ui.startup_screen`.

The stale contextual `bug_fix` planner route is removed. Bug fixes continue to
use the controlled coding workflow, while patch tools remain outside automatic
contextual routing. This resolves the inactive intent-route production policy
warning without widening execution authority.

## Migration

No data migration is required. Existing model-profile, memory, trace,
diagnostic, checkpoint, and workflow files retain their existing schema rules.
Follow [`docs/migrations/v3.0.0.md`](docs/migrations/v3.0.0.md) for installation,
validation, manual verification, and rollback steps.

## Security and CI

Progress is payload-free, non-persistent, and fail-soft. It receives bounded
titles and counters, not tool arguments, results, prompts, secrets, exceptions,
permission material, or execution authority. The release gate remains
read-only and runs compile, identity, policy consistency, the full test suite,
repository hygiene, smoke, and documentation checks on Windows and Linux for
Python 3.12, 3.13, and 3.14.

Elapsed UI state remains ephemeral. Aggregate request metrics are additive
diagnostic session-log metadata; they do not duplicate prompts or responses.

See [`docs/v3.0-architecture.md`](docs/v3.0-architecture.md) for the complete
architecture and compatibility boundary.

## Local validation status

On Windows with Python 3.12, the focused v3 UI, metrics, compatibility, and
release suite passed with 71 tests and 5 subtests. The full suite passed with
1112 tests and 139 subtests; 7 tests
were skipped because the process lacks Windows symlink privileges. Compileall,
identity, policy consistency, smoke, documentation, dependency consistency,
repository hygiene, and whitespace checks passed.

During pre-commit validation, every configured Release Manager command passed.
Its aggregate preparation status was pending only because the migration working
tree was intentionally uncommitted; the clean-tree gate is rerun after commit.

The final manual Windows PTY smoke used Ollama 0.31.2 with the configured
`qwen2.5-coder:14b` model. Two sequential requests returned independent exact
usage totals of 1,004 and 1,023 tokens. Cancellation stopped after 3.672 seconds,
returned the CLI to a usable prompt, and recorded nullable usage without a
false zero. A real redirected request exited successfully with no ANSI or
carriage-return redraw, 16 output lines, and exactly one completion summary.
