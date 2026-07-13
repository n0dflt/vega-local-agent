# Changelog

## Unreleased

Added:

* Immutable domain definitions and deterministic, independent domain registries.
* Built-in `coding` and `research` domain metadata covering current v2.7 intents.
* Immutable plugin manifests and tools with strict permission, capability,
  version, domain, and handler validation.
* Fail-closed plugin policy parsing and UTF-8-SIG policy loading.
* Exact-allowlist, package-prefix, trusted-root, and module-origin validation for
  trusted Python modules.
* Trusted-root-scoped dotted-module resolution that validates every parent
  package with explicit `PathFinder` search paths before executing source specs.
* Two-phase manifest collection and publication with immutable activation and
  bootstrap result models.
* Safe construction of isolated built-in and plugin tool registries.
* A supported plugin runtime factory that requires `PermissionEvaluator` while
  reusing the existing `ToolExecutor`.
* Tests for provenance, activation, multi-plugin failures, immutable state, and
  permission-enforced runtime construction.

Changed:

* Tool registry construction can produce an isolated combined registry without
  mutating the production `TOOL_REGISTRY`.
* Loaded tools enter the combined registry only after explicit permission,
  capability, domain, and collision checks.
* Architecture and roadmap documentation describe the v2.8 Plugin and Domain API.

Security:

* Plugins are disabled by default.
* File-path loading, Python entry points, and alternative factory hooks are
  forbidden.
* The supported production plugin path requires `PermissionEvaluator`; trusted
  Python code can still call a callable directly because this is not a sandbox.
* Missing or denied permission rules and missing or mismatched routing metadata
  keep handlers inactive and outside the combined registry.
* Parent packages are resolved without global `sys.path`, and module origins,
  files, package paths, and pre-existing `sys.modules` entries are checked before
  and after execution. Namespace, built-in, frozen, extension, sourceless, zip,
  and custom-loader modules are rejected.
* The Plugin API is not a security sandbox and accepts only explicitly trusted
  local modules.

## v2.7.2 - UTF-8 Documentation Fix

Fixed:

* Restored valid UTF-8 text in README.md.
* Restored valid UTF-8 Cyrillic text in docs/roadmap.md.
* Removed mojibake introduced while editing documentation through Windows PowerShell.
* Added a release test that rejects known encoding-corruption markers.

Changed:

* Runtime and documentation identity updated from v2.7.1 to v2.7.2.

Security:

* No runtime, permission, workflow, tool-routing, or execution behavior changed.

## v2.7.1 - Documentation and Licensing Patch

Added:

* Apache License 2.0 in the root LICENSE file.
* NOTICE file with VEGA copyright and licensing information.
* Clear project-status, capabilities, safety-model, and licensing sections in README.md.

Changed:

* Runtime and documentation version updated from v2.7.0 to v2.7.1.
* README introduction now describes VEGA as a local, safety-focused coding agent.
* Public repository usage terms are now explicitly defined.

Security:

* No runtime, permission, tool-routing, workflow, or execution behavior was changed.
* Existing fail-closed protections from v2.6.0 and v2.7.0 remain unchanged.

## v2.7.0 - Context-Aware Tool Orchestration

Added:

* Deterministic intent analysis, task interpretation, argument binding,
  capability-based tool planning, and structured execution plans.
* Fail-closed production tool catalog and explicit routing policy.
* Contextual plan preview and controlled explicit plan execution.
* Evidence-backed response synthesis for document analysis and code review.
* Dedicated tests for routing, planning, execution, formatting, and fallback behavior.

Changed:

* Supported natural-language requests can route to registered safe tools.
* Document analysis uses only `read_file` with a validated relative path.
* Code review uses `git_diff` with the existing workspace.
* Empty diffs return `No unstaged changes.` without invoking the model.
* Runtime and release identity updated to v2.7.0.

Security:

* The model receives no executor, registry, permissions, schemas, tokens,
  or callable tools and cannot trigger further execution.
* Unknown tools, invalid arguments, denied permissions, blocked paths, and
  tool-reported failures remain fail closed.
* Evidence is limited to 12,000 characters and synthesized output to 8,000.
* Model failures return the deterministic tool result without retries.
* Blocked, failed, project-search, preview, and `/plan run` paths do not synthesize.

## v2.6.0 - Permissions System

Added:

* Immutable permission models and the `allow`, `confirm`, and `deny` vocabulary
  across `low`, `medium`, `high`, and `critical` risk levels.
* Fail-closed production policy loading with exact registry-policy alignment.
* `PermissionEvaluator` enforcement in `ToolExecutor` and machine-readable
  permission error codes.
* One-time interactive approval and in-memory, exact-tool session grants where
  the production policy explicitly permits session scope.
* `/permissions`, `/permissions grants`, `/permissions revoke <tool_name>`, and
  `/permissions clear` lifecycle commands.
* A production executor factory that shares one process-local grant store between
  tool execution and permission commands.

Changed:

* All production tools are classified and enforced before argument validation and
  callable execution.
* Runtime, CLI identity, and release-check version updated to v2.6.0.

Security:

* Missing rules, policy/evaluator failures, invalid confirmation input, callback
  errors, and non-interactive confirmation-required actions fail closed.
* Session grants are never persisted or restored and cannot be created by a
  direct grant command.
* Workflow confirmation and interactive tool confirmation remain separate.

## v2.5.0 - Workflow Checkpoints and Safe Recovery

Added:

* Immutable workflow checkpoints at workflow start, stable waiting states, before
  and after patch application, after verification and review evidence, and terminal
  state transitions.
* Deterministic checkpoint payload integrity validation and equivalent-checkpoint
  deduplication.
* Recovery diagnosis for missing, corrupt, healthy, recoverable, and ambiguous
  active workflow state.
* Safe quarantine of corrupt active workflow JSON and atomic restoration of a
  validated `WorkflowRun` from the latest safe active checkpoint.
* `/workflow recovery-status [workflow_id]`, `/workflow checkpoints [workflow_id]`,
  and `/workflow recover <checkpoint_id> CONFIRM` commands.

Changed:

* Terminal workflow checkpoints move from active storage to checkpoint history.
* Checkpoint failure stops workflow progression instead of silently disabling
  checkpoint protection.
* Current version updated to v2.5.0.

Security:

* Malformed, unsafe, terminal, history-only, outdated, unsupported, and ambiguous
  checkpoints fail closed.
* Recovery restores workflow state only. It does not apply or roll back patches,
  resume execution, restore confirmation, run tests or review, execute terminal
  commands, or perform Git operations.
* Recovery requires the exact uppercase `CONFIRM` token and never continues the
  workflow automatically; `/workflow resume` remains a separate user action.
* Recovery uses process-local locking, active checkpoints only, and latest-safe
  selection. Older checkpoints cannot be selected manually, and checkpoint and
  workflow archival are not a single multi-file database transaction.

## v2.4.0 - Controlled Review Pipeline

Added:

* Read-only review after every successful workflow verification.
* Strictly validated findings with severity, category, evidence, recommendation,
  and blocking status.
* Safe review policy with critical and high findings always blocking.
* Persistent review history and `/workflow review` reporting.
* Review state and explicit `review_findings` patch-request reason.

Changed:

* Blocking review findings continue through the existing patch, confirmation,
  verification, and review path.
* Every review-fix patch requires its own explicit confirmation and consumes the
  existing three-iteration patch limit.
* Resume restores saved review outcomes without invoking Reviewer again.
* Current version updated to v2.4.0.

Security:

* Reviewer receives only bounded workflow evidence and no Patch Tools, Tool
  Executor, shell access, rollback, or file-writing capability.
* Invalid JSON, invalid findings, provider failures, and blocking findings at the
  patch limit fail closed.
* Review Pipeline never changes files automatically and never reviews unrelated
  working-tree changes.

## v2.3.0 - Controlled Test-Fix Loop

Added:

* Repeated verification after explicitly supplied fixing patches.
* A controlled transition back to waiting for another patch after a real test
  failure.
* Separate confirmation for every new patch iteration.
* Persistent history of applied patches and their verification results.
* Accumulation of changed files across patch iterations.

Changed:

* Workflows may continue through at most three patch iterations before stopping.
* Test Tools results distinguish a real test failure from failure of the test
  runner itself. Runner failures remain infrastructure errors and do not enter
  the fix loop.
* VEGA waits for the user to provide a real pending Patch Tools artifact; it does
  not generate a fixing patch automatically.

Security:

* Exhausting the three-iteration limit ends the workflow fail-closed and requires
  manual intervention.
* Persisted patch and verification evidence prevents an applied patch from being
  applied again and prevents a saved verification from being rerun during resume.
* Automatic rollback and unbounded autonomous test-fix loops are not enabled.

## v2.2.0 - Coding Workflows

Added:

* Persistent workflow models, registry, engine, and active/history storage.
* Feature, bugfix, and behavior-preserving refactor workflows.
* `/workflow` list, start, status, resume, confirm, cancel, and history commands.
* State, persistence, confirmation, CLI, and compatibility tests.

Changed:

* Coding tasks can use an ordered, resumable process built on existing context,
  Patch Tools, Test Tools, and confirmation layers.
* Current version updated to v2.2.0.

Security:

* File changes remain blocked until explicit confirmation.
* Only one workflow may be active, and verification is executed at most once.
* Terminal workflow states cannot be resumed.

## v2.1.0 - Structured Command Execution and Controlled Tool Orchestration

Added:

* `CommandExecutor` for structured execution of routed slash commands.
* `ToolExecutor` for controlled invocation of registered tools.
* Structured command and tool request, result, and status types.
* Runtime integration for one command executor per session.
* Unit and integration tests for the executor layer.

Changed:

* Slash commands are executed through `CommandExecutor`.
* `/file`, `/git`, and `/tools list` pass through `ToolExecutor`.
* One `ToolExecutor` instance is reused for each runtime session.
* `/docs` uses a dedicated compatibility adapter.
* Command failures receive structured statuses and `COMMAND_ERROR` logging.

Security:

* Tool names are selected only by fixed command-handler code.
* Users cannot invoke an arbitrary registered tool.
* The model and `AgentOrchestrator` do not receive `ToolExecutor`.
* Write, terminal, test, internet, web, and patch commands are not routed through the new tool-execution path.
* Automatic model-driven execution loops are not enabled.

## v2.0.0 - Agent Orchestration Foundation

Added:

* Deterministic intent classification.
* Deterministic slash-command routing.
* Shared execution context for one VEGA session.
* Process-local confirmation manager.
* Top-level agent orchestrator.
* Isolated Ollama HTTP client.
* Runtime and CLI entrypoint separation.
* Unit and integration tests for the orchestration layer.

Changed:

* `scripts/vega.py` is now a thin CLI entrypoint.
* Main session logic moved into `core/agent_runtime.py`.
* User input is routed before command or chat handling.
* Chat history is managed through `ExecutionContext`.
* Ollama networking is isolated from the main runtime.
* Current version updated from v1.12.0 to v2.0.0.

Security:

* Input and slash-command routing remain deterministic.
* Model-driven automatic tool execution is not enabled.
* Existing Patch Tools confirmation remains active.
* Confirmation state is limited to one pending action per session.
* Existing workspace, terminal, internet, patch, and Git policies remain authoritative.

## v1.12.0 - Release Manager

Added:

* Read-only release policy in `config/release_policy.json`.
* Release readiness tools in `tools/release_tools.py`.
* `/release`, `/release status`, `/release check`, and `/release notes` commands.
* Release Manager registration in the shared Tool Registry.
* Branch, working-tree, required-file, documentation, identity, compilation, and test checks.
* In-memory release-notes generation from the current `CHANGELOG.md` section.
* Release notes storage in `docs/releases/`.
* Unit and command-handler tests for Release Manager.

Changed:

* CLI help and available-command output include Release Manager.
* Generated architecture, command, and security documentation includes v1.12.0 state.
* Current version updated from v1.11.0 to v1.12.0.

Security:

* Release Manager is read-only.
* Automatic commit, tag, push, and GitHub release publishing are forbidden by policy.
* Release checks accept only predefined validation command identifiers.
* Release paths must remain inside the active project root.

## v1.11.0 - Agent Modes

Added:

* Configurable agent modes in `config/modes.json`.
* Mode registry and process-local mode session in `core/agent_modes.py`.
* `/mode`, `/mode list`, `/mode set <name>`, and `/mode reset` commands.
* Architect, coder, reviewer, debugger, teacher, and release-manager modes.
* Active mode instructions in the model system context.
* Unit and command-handler tests for mode loading, switching, resetting, and validation.

Changed:

* VEGA starts in the `coder` mode by default.
* CLI help now includes Agent Mode commands.
* Patch application and rollback receive the active mode policy.
* Current version updated from v1.10.0 to v1.11.0.

Security:

* Modes without code-change permission block `/patch apply` and `/patch rollback`.
* Unknown mode names are rejected without changing the active mode.
* Mode state is process-local and resets when VEGA restarts.

## v1.10.0 - Documentation Builder

Added:

* Documentation policy in `config/documentation_policy.json`.
* Managed documentation validation for architecture, commands, and security documents.
* `/docgen`, `/docgen status`, `/docgen check`, and `/docgen build` commands.
* Safe generated documentation blocks with explicit start and end markers.
* Pending documentation patch generation through Patch Tools.
* Documentation status and version-reference checks.
* `docs/security.md`.
* Registered Documentation Builder tools.
* Predefined `/test docs` test group.
* Unit, command-handler, CLI-routing, and builder tests.

Changed:

* Test Runner expanded from eight to nine predefined groups.
* CLI help and available command output include Documentation Builder.
* README command reference and project status updated.
* Current version updated from v1.9.0 to v1.10.0.

Security:

* Missing managed documents are not created automatically.
* Documentation patches are never applied automatically.
* Builds are restricted to the active VEGA project root.
* Manual documents are excluded from generated updates.
* Patch application remains a separate operation requiring the exact `CONFIRM` token.

## v1.9.0 - Controlled Internet Layer

Added:

* Explicit `/internet`, `/internet status`, `/internet on`,
  and `/internet off` commands.
* Read-only `/web fetch <https-url>` command.
* Strict network policy in `config/internet_policy.json`.
* Process-local internet state that starts disabled.
* HTTPS-only URL and standard-port validation.
* Protection against localhost, private, reserved, and
  other non-public network addresses.
* Blocking of redirects, binary content, and oversized responses.
* Bounded request timeout and response size.
* Sanitized audit logging in `logs/web/web_requests.jsonl`.
* Registered internet and web tools.
* Four predefined web test groups.
* Network, tool, command-handler, and CLI tests.

Changed:

* Runtime internet indicators now follow the current process state.
* Test Runner expanded from four to eight predefined groups.
* Current version updated from v1.8.0 to v1.9.0.

Security:

* Internet access remains OFF by default.
* Proxy environment variables are ignored by controlled requests.
* URL queries and fragments are excluded from audit logs.
* Automatic redirects are disabled to reduce SSRF risk.



## v1.0.0 - Stable Local Agent Release

- Stable CLI release.
- Added `/about` command.
- Improved `/help`.
- Removed old development check script.
- Added `requirements.txt`.
- Added `.gitignore`.
- Improved README and release documentation.
- Confirmed document reader, analyzer, local RAG search, model profiles, and doctor diagnostics.

## v0.9.0 - Runtime Polish & Smarter Docs

- Added `/model status`.
- Added `/model install-help`.
- Added `/doctor`.
- VEGA no longer exits only because the selected model is missing.
- Improved `/docs ask` with extractive answers and sources.
- Improved runtime diagnostics.

## v0.8.0 - Global Document Analysis & Model Profiles

- Added document analyzer.
- Added `/docs analyze`.
- Added `/docs summarize`.
- Added `/docs ask`.
- Added optional PDF/DOCX support.
- Added model profiles: `fast`, `code`, `docs`, `deep`.
- Added `scripts/smoke_test.py`.

## v0.7.0 - Document Reader

- Added local document reader.
- Added local document index.
- Added `/docs list`.
- Added `/docs index`.
- Added `/docs search`.
- Added `/docs read`.

## v0.6.0 - Project Stabilization

- Stabilized project architecture.
- Prepared GitHub release baseline.
- Added GitHub release checkpoint.

## v0.5.0

Added:

* Task Console
* /workspace command
* /task command
* /task new <title>
* /task plan
* /task step <text>
* /task done <number>
* /task note <text>
* /task review
* /task close
* /task clear
* /q exit alias
* core\task_manager.py
* ui\task_views.py
* data\tasks storage
* task archive storage
* task checks in health-check

Changed:

* version updated to v0.5.0
* /help updated with Task Console commands
* /status now shows Task Console state
* startup command hint updated

## v0.3.1

Stabilization release for Documents / RAG.

Added:

* /status command
* improved /docs list
* improved /docs search <query>
* typo hints for /docs commands
* health-check script: scripts/check_v033.py

Changed:

* version updated to v0.3.1
* documents index handling improved
* service files are hidden from /docs list
* service files are ignored by document ingestion

Fixed:

* empty /docs search query handling
* missing index handling
* broken index handling
* accidental display of .gitkeep in documents list

## v0.3.0

Initial Documents / RAG scaffold.

## v0.2.x

Stable local CLI coding-agent foundation.
