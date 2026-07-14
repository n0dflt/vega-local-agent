# VEGA

VEGA is a local, safety-focused coding agent for working with source code,
project structure, development tasks, Git, local documents, and controlled tools.

The project runs locally, uses Ollama models, and keeps tool execution behind
explicit registries, argument validation, permission policies, and confirmation
gates.

## Current version

```text
v2.12.0 - Local State Integrity & Recovery
```

The previous stable release is:

```text
v2.10.0 - Production Reliability and Execution Traces
```

## Project status

VEGA is under active development.

The current version is intended for:

* local development;
* controlled project assistance;
* experimentation with local AI agents;
* portfolio demonstration;
* research into safe tool orchestration.

VEGA is not currently presented as a production-ready autonomous agent.

## Key capabilities

* Local CLI coding agent
* Ollama model support
* Project and file analysis
* Documents and local RAG
* Confirmed patch application and rollback
* Read-only Git inspection
* Persistent project memory
* Controlled terminal commands
* Automated test groups
* Controlled HTTPS access
* Documentation and release checks
* Coding workflows with verification and review
* Workflow checkpoints and recovery
* Fail-closed tool permissions
* Context-aware natural-language tool routing
* Validated cross-layer production runtime snapshot
* Deterministic model selection and bounded synthesis context
* Opt-in bounded and redacted local execution diagnostics
* Explicit local runtime reports and bounded trace aggregates

## Safety model

VEGA does not give the language model direct access to:

* the Tool Executor;
* registered callable tools;
* permission or confirmation tokens;
* unrestricted shell execution;
* arbitrary filesystem paths;
* automatic Git commits or publishing.

Natural-language requests are converted into structured execution plans.
Tool names and arguments are validated by VEGA before execution.

Protected operations remain subject to explicit permission and confirmation
policies. Unknown tools, invalid arguments, blocked paths, missing permission
rules, and policy errors fail closed.

## License

VEGA is licensed under the Apache License, Version 2.0.

See:

```text
LICENSE
NOTICE
```

Copyright 2026 n0dflt.

## Requirements

* Windows
* Python 3.12+
* Ollama
* Recommended local Ollama model: qwen2.5-coder:14b

## Run

From project root:

```bat
python scripts\vega.py
```

## Commands

```text
/help
/status
/workspace
/model
/model status
/model install-help
/project
/log
/doctor
/docs
/docs list
/docs index
/docs search <query>
/docs read <filename>
/docs analyze <filename>
/docs summarize <filename>
/docs ask <question>
/docs formats
/file
/file list <path>
/file read <path>
/file find <name>
/file search <query>
/file summary <path>
/patch
/patch list
/patch list pending
/patch list applied
/patch list rolled_back
/patch show <patch_id>
/patch propose <target> <proposal> [reason]
/patch apply <patch_id> CONFIRM
/patch rollback <patch_id> CONFIRM
/tools list
/memory
/memory add <decision|fact|constraint> <text>
/memory list [kind]
/memory search <query>
/memory stats
/run
/run list
/run <command-id>
/model fast
/model code
/model docs
/model deep
/task
/task new <title>
/task plan
/task step <text>
/task done <number>
/task note <text>
/task review
/task close
/task clear
/test
/test list
/test all
/test terminal
/test terminal-tools
/test terminal-commands
/test web
/test web-tools
/test web-commands
/test web-cli
/test docs
/internet
/internet status
/internet on
/internet off
/web fetch <https-url>
/mode
/mode list
/mode set <architect|coder|reviewer|debugger|teacher|release_manager>
/mode reset
/docgen
/docgen status
/docgen check
/docgen build
/release
/release status
/release check
/release notes
/exit
/bye
/q
```

## VEGA v1.2.0 — Safe File Tools

VEGA provides read-only tools for listing project directories, reading bounded UTF-8
text files, finding files, searching text, and creating deterministic file summaries.
All paths are relative to the project root. Parent-directory escapes, service folders,
sensitive files, private keys, certificates, and binary files are blocked.

```text
/file
/file list .
/file read core\agent_runtime.py
/file find agent_runtime.py
/file search "class AgentRuntime"
/file summary core\agent_runtime.py
/tools list
```

These commands cannot write or delete files and cannot execute shell or Git commands.

## VEGA v1.3.0 - Confirmed Patch Tools

VEGA can prepare, inspect, apply, and roll back controlled changes to existing
UTF-8 text files inside the project workspace.

```text
/patch
/patch list
/patch list pending
/patch list applied
/patch list rolled_back
/patch show <patch_id>
/patch propose <target> <proposal> [reason]
/patch apply <patch_id> CONFIRM
/patch rollback <patch_id> CONFIRM
```

Applying and rolling back patches requires the exact `CONFIRM` token.
SHA-256 verification blocks stale patches from overwriting later changes.
An exact byte-level backup is created before a patch is applied.

## VEGA v1.5.0 - Project Memory

Project Memory stores project decisions, verified facts, and constraints explicitly
saved by the user. Data is stored locally in
`data/memory/project_memory.json` and persists between VEGA runs.

Memory entries are created only through explicit `/memory add` commands.
VEGA does not infer or save memory automatically from conversations.

```text
/memory
/memory add decision <text>
/memory add fact <text>
/memory add constraint <text>
/memory list [kind]
/memory search <query>
/memory stats
```

Version 1.5.0 intentionally has no delete, edit, clear, import, or export commands.

A bounded selection of saved entries is added only to the current model request.
Project Memory does not accumulate inside the chat history and does not override
VEGA system safety rules.

If the memory storage is invalid or corrupted, VEGA reports a warning and
continues chatting without Project Memory.

## Task Console

VEGA v0.5.0 adds a local task console for project work.

Commands:

```text
/workspace
/task
/task new <title>
/task plan
/task step <text>
/task done <number>
/task note <text>
/task review
/task close
/task clear
```

Example:

```text
/task new Improve document search
/task step Add highlighting for matching text
/task step Add preview length limit
/task done 1
/task review
```

Task storage:

```text
data\tasks\current_task.json
data\tasks\archive\
```

## Documents / RAG

VEGA v1.0.0 can read local documents, build a simple local index, search it, and run deterministic local analysis.

Put documents here:

```text
data\documents
```

Create or rebuild the index:

```text
/docs index
```

Search indexed documents:

```text
/docs search <query>
```

Read a document:

```text
/docs read <filename>
```

Index file:

```text
data\index\documents_index.json
```

Supported formats:

```text
.txt, .md, .py, .json, .csv
optional .pdf, optional .docx
```

Analysis commands:

```text
/docs analyze <filename>
/docs summarize <filename>
/docs ask <question>
/docs formats
```

`/docs ask <question>` shows an extractive answer plus numbered sources.

## v1.0.0 - Stable Local Agent Release

Model:

```text
/model
/model status
/model install-help
/model fast
/model code
/model docs
/model deep
```

Doctor:

```text
/doctor
```

Docs:

```text
/docs ask <question>
```

Runtime behavior:

```text
VEGA no longer exits only because the selected model is missing.
Document commands remain available without the model.
```

Recommended setup:

```bat
ollama pull qwen2.5-coder:14b
```

Optional:

```bat
ollama pull qwen2.5-coder:32b
```

## v0.8.0 - Global Document Analysis & Model Profiles

Documents:

```text
data\documents
data\index\documents_index.json
```

Commands:

```text
/docs list
/docs index
/docs search <query>
/docs read <filename>
/docs analyze <filename>
/docs summarize <filename>
/docs ask <question>
/docs formats
```

Supported formats:

```text
.txt
.md
.py
.json
.csv
optional .pdf
optional .docx
```

Model profiles:

```text
/model
/model status
/model install-help
/model fast
/model code
/model docs
/model deep
```

Recommended models:

```text
qwen2.5-coder:14b as main
qwen2.5-coder:32b as deep mode only
```

Optional Ollama setup:

```bat
ollama pull qwen2.5-coder:14b
ollama pull qwen2.5-coder:32b

ollama create vega-code-14b -f .\ollama\Modelfile.14b
ollama create vega-deep-32b -f .\ollama\Modelfile.32b
```

## Smoke Test

Run:

```bat
python scripts\smoke_test.py
```

Expected result:

```text
Result: OK
```

## VEGA v1.7.0 — Safe Terminal Tools

Safe Terminal Tools execute only predefined local diagnostics, compilation, and
automated checks. Arbitrary shell commands and user-supplied argv are not supported.
Every command runs from the project root with `shell=False`, a fixed timeout, and
bounded stdout and stderr.

```text
/run
/run list
/run python-version
/run compile
/run tests
/run smoke
/run identity
```

Allowed commands are declared in:

```text
config\allowed_commands.json
```

Execution metadata is recorded without command output or environment values in:

```text
logs\terminal\terminal_commands.jsonl
```

Editing the JSON policy does not bypass built-in executable and path validation.
Dangerous executables, absolute paths, parent traversal, UNC paths, symlink escapes,
and additional CLI arguments remain blocked.

## VEGA v1.8.0 — Test Runner

Test Runner executes predefined pytest groups through the Safe Terminal Tools
layer. Arbitrary pytest arguments, custom test paths, and shell commands are
not accepted.

```text
/test
/test list
/test all
/test terminal
/test terminal-tools
/test terminal-commands
```

## VEGA v1.9.0 - Controlled Internet Layer

Controlled Internet Layer provides explicit, read-only HTTPS access.
Internet access is disabled whenever a new VEGA process starts and
must be enabled manually for the current process.

```text
/internet
/internet status
/internet on
/internet off
/web fetch <https-url>
```

Network policy is stored in:

```text
config\internet_policy.json
```

The network safety layer blocks:

```text
HTTP and non-standard ports
localhost and non-public IP addresses
credentials embedded in URLs
automatic redirects
binary responses
oversized responses
```

Every request uses timeout and response-size limits.
Request metadata is written to:

```text
logs\web\web_requests.jsonl
```

Query parameters and fragments are removed before audit logging.
v1.9.0 does not include a search provider, browser automation,
form submission, authentication, or file downloads.

## VEGA v1.10.0 - Documentation Builder

Documentation Builder validates the configured project documentation and
creates controlled pending patches for managed documents.

```text
/docgen
/docgen status
/docgen check
/docgen build
```

The documentation policy is stored in:

```text
config/documentation_policy.json
```

Managed documents:

```text
docs/architecture.md
docs/commands.md
docs/security.md
```

`/docgen build` does not modify these files directly. It creates pending
Patch Tools proposals that must be inspected and applied separately with the
exact `CONFIRM` token.

Manual documents remain under direct human control:

```text
README.md
CHANGELOG.md
docs/roadmap.md
```

Documentation Builder does not create missing files automatically, apply
patches automatically, rewrite release history, or bypass the active project
root.

The predefined test group is:

```text
/test docs
```

## Project status

Historical stable checkpoint for that documentation milestone:

```text
v2.7.0 - Context-Aware Tool Orchestration
```

Next stage recorded at that milestone:

```text
v2.8.0 - Plugin and Domain API
```

## VEGA v1.12.0 - Release Manager

VEGA includes a read-only Release Manager for checking whether the project is ready for release.

```text
/release
/release status
/release check
/release notes
```

Release Manager validates the configured branch policy, Git working-tree state, required project files, documentation, identity checks, compilation, and tests.

It does not commit, tag, push, or publish GitHub releases automatically.

## VEGA v2.0.0 - Agent Orchestration Foundation

VEGA v2.0.0 establishes the orchestration layer used by the interactive CLI:

```text
scripts/vega.py
    -> core/agent_runtime.py
        -> core/orchestrator.py
            -> core/intent_router.py
            -> core/command_router.py
            -> core/execution_context.py
            -> core/confirmation_manager.py
        -> core/ollama_client.py
```

The orchestrator classifies input and routes explicit slash commands deterministically. A shared execution context owns the model, prompt, mode, confirmation state, and message history for one session. Ollama HTTP handling is isolated from the runtime.

v2.0.0 does not enable automatic model-driven tool execution. Existing workspace, terminal, internet, patch, and Git safety restrictions remain active and authoritative.

## VEGA v2.1.0 - Structured Command Execution and Controlled Tool Orchestration

Slash commands now move from deterministic routing through `CommandExecutionRequest` and `CommandExecutor` before reaching existing handlers. Command failures have structured statuses and are recorded as `COMMAND_ERROR` events.

The read-only `/file`, `/git`, and `/tools list` command paths use one controlled `ToolExecutor` for each runtime session. Command handlers select fixed registered tool names; users cannot supply an arbitrary tool name.

The model and `AgentOrchestrator` do not receive `ToolExecutor`. Automatic model-driven tool calling and autonomous execution loops are not included in v2.1.0.

## VEGA v2.2.0 - Coding Workflows

VEGA provides persistent, confirmation-gated `feature`, `bugfix`, and `refactor`
workflows. Runs persist under `data/workflows/active/` and terminal runs move to
`data/workflows/history/`.

```text
/workflow list
/workflow start feature "<task>"
/workflow start bugfix "<task>"
/workflow start refactor "<task>"
/workflow attach-patch <pending_patch_id>
/workflow link-task <task_id>
/workflow status
/workflow resume
/workflow confirm
/workflow cancel
/workflow history
```

Start performs only read-only analysis and planning, then stops at `waiting_patch`.
`attach-patch` accepts only a real pending Patch Tools artifact and advances to
`waiting_confirmation` without changing files. No patch is applied before explicit
confirmation. The optional legacy `--patch` start form remains confirmation-gated.
Task plans remain inside the workflow unless `/workflow link-task <task_id>` is
invoked explicitly.

## VEGA v2.3.0 - Controlled Test-Fix Loop

After an explicitly confirmed patch is applied, the workflow runs controlled
verification. A successful path is:

```text
patch
-> confirmation
-> apply
-> verification
-> completed
```

When verification reports a real test failure, the workflow preserves the patch
and verification history and waits for another real pending Patch Tools artifact
from the user:

```text
patch
-> confirmation
-> apply
-> failed verification
-> waiting for another patch
-> new confirmation
-> apply
-> verification
```

Every patch requires its own explicit confirmation. VEGA does not generate the
next fixing patch, run an infinite autonomous loop, or automatically roll back an
applied patch. A workflow permits at most three patch iterations. If verification
still fails after the limit is reached, the workflow stops fail-closed and requires
manual intervention.

## VEGA v2.4.0 - Controlled Review Pipeline

After each successful verification, VEGA runs a bounded, read-only review of only
the patches and files recorded by the active workflow:

```text
patch -> confirmation -> apply -> verification -> review -> completed
```

Critical and high findings are blocking. Info, low, and medium findings are kept
in the review report but do not prevent completion. Blocking findings return the
workflow to `waiting_patch` with reason `review_findings`; the user must supply a
real pending Patch Tools artifact, confirm it separately, and pass verification
before another review runs. Review fixes share the existing three-patch limit.

`/workflow review` shows the latest structured report. Resume reuses persisted
verification and review evidence instead of applying patches or invoking Reviewer
again. Reviewer has no Patch Tools, shell, or file-writing capability, and invalid
or unavailable provider output fails closed.

## VEGA v2.5.0 - Workflow Checkpoints and Safe Recovery

VEGA records immutable workflow checkpoints at controlled boundaries: workflow
start, stable waiting states, before and after patch application, after verification
and review evidence is recorded, and at terminal state transitions. Payloads use a
deterministic representation for integrity validation, equivalent checkpoints are
deduplicated, and terminal workflow checkpoints move to history. A checkpoint
failure stops workflow progression instead of silently disabling protection;
malformed or unsafe checkpoint data fails closed.

The Recovery Manager diagnoses missing, corrupt, healthy, and ambiguous active
workflow state. It can select only the latest safe active checkpoint, move corrupt
active workflow JSON unchanged into managed quarantine, and atomically restore a
validated `WorkflowRun`. Terminal, history-only, outdated, malformed, unsupported,
and ambiguously sequenced checkpoints are refused.

Recovery inspection and restoration use these commands:

```text
/workflow recovery-status
/workflow recovery-status <workflow_id>

/workflow checkpoints
/workflow checkpoints <workflow_id>

/workflow recover <checkpoint_id> CONFIRM
```

Recovery restores serialized workflow state only. It does not apply or roll back
patches, restore process-local confirmation, resume workflow execution, run tests
or review, execute terminal commands, or perform Git operations. After reviewing
the restored state, the user must run `/workflow resume` separately.

Recovery intentionally uses process-local locking. Only active checkpoints are
recoverable, and an older checkpoint cannot be selected manually. Checkpoint and
workflow archival are separate filesystem operations rather than one multi-file
database transaction. Recovery never continues execution automatically, and the
exact uppercase token `CONFIRM` is mandatory.

## VEGA v2.6.0 - Permissions System

Every production tool passes through a fixed, exactly aligned permission policy
before argument validation and callable execution. Permission effects are
`allow`, `confirm`, and `deny`; risk levels are `low`, `medium`, `high`, and
`critical`. Allowed tools execute normally, confirmation-required tools need an
explicit approval, and denied or unclassified tools never execute. Missing rules
and evaluator failures fail closed, while unregistered names retain the
`unknown_tool` result.

Interactive confirmation accepts `y` or `yes` for one invocation. Eligible tools
also offer a process-local `session` grant. Session grants start empty, apply to
one exact tool, are never persisted, and can only arise from an actual
confirmation-required invocation when the production policy permits session
scope. Empty or unknown input, `n`/`no`, EOF, interruption, callback failure, and
non-interactive execution all reject the action. Internal confirmation metadata
is never exposed to users or passed to tool callables.

```text
/permissions
/permissions grants
/permissions revoke <tool_name>
/permissions clear
```

There is no `/permissions grant <tool_name>` command. Workflow confirmation in
`core/confirmation_manager.py` remains separate from interactive tool-permission
confirmation in `core/tool_confirmation.py`.

## VEGA v2.7.0 - Context-Aware Tool Orchestration

VEGA can interpret supported natural-language requests and map them
deterministically to registered safe tools.

The contextual pipeline separates:

```text
user request
    -> intent analysis
    -> task interpretation
    -> capability-based planning
    -> argument validation
    -> permission evaluation
    -> ToolExecutor
    -> contextual response
```

The model does not receive the executor, tool registry, schemas,
permissions, tokens, or callable tools. Model output cannot trigger
additional tool execution.

Document analysis plans only `read_file` with a validated safe relative
path. Code review uses `git_diff` with the existing workspace.

An empty Git diff returns:

```text
No unstaged changes.
```

without invoking the model.

Contextual synthesis receives only the original request, resolved intent,
selected tool name, bounded evidence, configured model name, and the
injected Ollama chat callable.

Evidence is limited to 12,000 characters. Accepted synthesized output is
limited to 8,000 characters.

If the model is unavailable, missing, returns an empty response, or raises
an exception, VEGA preserves successful tool execution and returns the
existing deterministic result. Automatic synthesis retries are not used.

Blocked, failed, project-search, preview, and `/plan run` paths never invoke
contextual synthesis. Protected actions remain controlled by the Permission
System and explicit confirmation policy.

## Plugin and Domain API

VEGA v2.8 introduces an architectural API for domains and trusted local plugin
modules. A domain is immutable metadata that groups intents, capabilities, and
the names of existing tools. The built-in `coding` and `research` definitions
do not move or duplicate tool implementations and do not change the v2.7
planner routes.

A plugin is an immutable manifest returned by the one supported factory,
`get_plugin_manifest()`. Plugins are disabled by default in
`config/plugin_policy.json`. Enabling a module requires both an exact module
allowlist entry, an allowed package prefix, and an origin inside an existing
trusted root under the project root. The module origin is checked before and
after execution. A trusted-root-scoped resolver walks every dotted-name package
component with `PathFinder` and explicit project-local search paths, validates
all parent packages before executing them, and then executes only the validated
source specs. Namespace, built-in, frozen, extension, sourceless, zip, custom,
path-based, and entry-point loading are not supported. Pre-existing
`sys.modules` entries must match the validated origins, files, and package paths.

Loading and activation are separate. A validated manifest remains loaded, but
its tool becomes active only when its domain is enabled, an explicit non-deny
permission rule exists, and contextual metadata exactly matches its routing
permission and capabilities. Inactive handlers are absent from the combined
registry. Bootstrap collects and validates the complete manifest set before it
publishes immutable snapshots and mappings; import and factory side effects
cannot be rolled back. Resolver failures remove only modules and parent
attributes added by that resolver call; arbitrary Python side effects remain.

The supported production plugin execution path is
`build_plugin_tool_executor()`, which requires a `PermissionEvaluator` and uses
the existing `ToolExecutor`. The Plugin API is not a sandbox: trusted Python
code can still call a handler directly. Permission and contextual-routing
configuration files are never modified automatically.

## VEGA v2.9.0 - Model Selection and Context Optimization

VEGA maps supported contextual intents to validated model profiles, preserves
manual profile selection, falls back only to installed models, and applies
per-profile context budgets before optional evidence synthesis. A missing or
failing model never reruns a tool or discards a successful deterministic tool
result.

## VEGA v2.10.0 - Production Reliability and Execution Traces

VEGA v2.10 composes routing metadata, domains, tools, plugin activation,
permissions, model profiles, and context budgets into one immutable validated
production snapshot. Fatal configuration drift blocks tool execution before a
normal handler is published. The supported execution path remains:

```text
contextual runtime -> execute_plan() -> PlanExecutor -> ToolExecutor
```

Execution traces observe that path without invoking tools themselves. A trace
contains only bounded machine decisions and stable codes; it excludes request
text, prompts, evidence, arguments, results, payloads, handlers, callbacks,
tokens, grants, environment values, secrets, full local paths, URL query
parameters, and raw exceptions.

Persistence is disabled by default. Set `VEGA_EXECUTION_TRACE` to `1`, `true`,
`yes`, or `on` to append UTF-8 JSONL to
`logs/diagnostics/execution-traces.jsonl`. The active file is limited to 5 MiB
and retains one `.1` backup. Locking is process-local only; v2.10 does not claim
interprocess-safe appends. `/doctor trace latest` prints only a safe allowlisted
summary.

Mutable model-profile and task state is local, ignored, and untracked. Model
profile writes use atomic replacement. Failure paths return stable safe
messages/codes, and failed synthesis preserves the completed deterministic
response. See [v2.10.0 release notes](docs/releases/v2.10.0.md) for migration
impact and known limitations.

## VEGA v2.11.0 - Runtime Diagnostics Evolution

VEGA v2.11 adds one local-only diagnostics observer over the existing production
runtime. `/doctor` builds a bounded immutable report, `/doctor trace status` and
`/doctor trace summary` inspect the opt-in trace store, and `/doctor export`
atomically writes an allowlisted JSON report under
`logs/diagnostics/reports/`. No report is created without that explicit command.

Trace persistence remains controlled by `VEGA_EXECUTION_TRACE`. The 5 MiB active
file limit is unchanged, while validated policy now retains three backups by
default and bounds files, records, report bytes, and report retention. Existing
valid v2.10 JSONL records remain readable.

Diagnostics never execute tools, call a model, send telemetry, or include
prompts, user text, evidence, file contents, tool payloads, command output,
credentials, absolute user paths, raw exceptions, or tracebacks. Locking remains
process-local rather than interprocess-safe. See the
[v2.11 architecture](docs/v2.11-architecture.md) and
[v2.11.0 release notes](docs/releases/v2.11.0.md).

## VEGA v2.12.0 - Local State Integrity & Recovery

VEGA v2.12 coordinates trace and diagnostic-report mutations across processes
with bounded Windows and POSIX file locks. Interrupted JSONL tails can be
recovered explicitly, complete corruption is quarantined, and recognized stale
atomic-write files are cleaned without touching unrelated project files.

Use `/doctor state status` for a read-only bounded view and
`/doctor state repair` for the only explicit repair path. Trace persistence
remains opt-in, diagnostics remain local observer-only state, and the supported
execution route through `PlanExecutor` and `ToolExecutor` is unchanged.

See the [v2.12 architecture](docs/v2.12-architecture.md) and
[v2.12.0 release notes](docs/releases/v2.12.0.md).
