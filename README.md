# VEGA

VEGA is a local project coding-agent for working with code, project structure, local tasks, and local documents.

## Current version

v2.2.0

## Features

* Local CLI agent
* Ollama model support
* Project-focused coding assistant
* ASCII-only startup screen
* Session logs
* Task Console
* Documents / RAG commands
* Confirmed Patch Tools with SHA-256 verification and rollback
* Local document indexing
* Search over indexed documents
* Local document analysis and summaries
* Model profiles
* Runtime doctor
* Runtime status command
* Smoke-test script
* Local Project Memory with explicit storage and bounded model context
* Safe Terminal Tools with predefined validation commands
* Controlled Internet Layer with explicit session-level enablement and safe HTTPS fetching
* Documentation Builder with policy validation, managed documents, and pending patch generation
* Process-local Agent Modes for architecture, coding, review, debugging, teaching, and release management
* Read-only Release Manager with policy validation, release checks, and release-notes generation
* Agent Orchestration Foundation with deterministic routing, shared session state, runtime isolation, and an extracted Ollama client
* Structured Command Execution with typed requests, results, and statuses
* Controlled Tool Orchestration for the read-only `/file`, `/git`, and `/tools list` commands

## Requirements

* Windows
* Python 3.14+
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

## VEGA v1.2.0 вЂ” Safe File Tools

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

Current stable checkpoint:

```text
v2.2.0 - Coding Workflows.
```

Next planned stage:

```text
v2.2.0 - Coding Workflows.
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
