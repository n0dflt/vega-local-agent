# Changelog

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
