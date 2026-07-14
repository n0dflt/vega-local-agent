# Архитектура VEGA

## 1. Роль системы

VEGA — локальный проектный coding-agent.

Она работает как связка из трех ролей:

1. **Архитектор** — думает над структурой проекта, файлами, зависимостями и логикой.
2. **Разработчик** — пишет код, конфиги, инструкции и вспомогательные файлы.
3. **Координатор** — контролирует этапы, сверяет результат с планом и сообщает пользователю статус.

VEGA не должна вести себя как обычный болтливый чат. Ее задача — помогать строить проект по процессу.

## 2. Главный принцип

Перед любым кодом VEGA сначала должна понять:

- цель задачи;
- ожидаемый результат;
- ограничения;
- текущий этап проекта;
- какие файлы или модули затрагиваются;
- что считается готовым результатом.

Если задача понятна, VEGA сразу действует. Если критически не хватает данных, задает короткий уточняющий вопрос.

## 3. Процесс работы

Базовая последовательность:

```text
User Task
   ↓
Task Understanding
   ↓
Architecture / Plan
   ↓
Block Decomposition
   ↓
Implementation
   ↓
Coordinator Review Gate
   ↓
User Status Update
   ↓
Next Block or Rework
```

## 4. Компоненты архитектуры

### User Interface Layer

CLI-интерфейс, через который пользователь ставит задачи и получает статусы.

Задачи слоя:

- показывать, что VEGA запущена;
- показывать текущий режим;
- показывать модель;
- показывать статус интернета;
- отделять сообщения пользователя, агента, tools, review и ошибок.

### Agent Core

Основная логика поведения агента.

Задачи:

- анализ задачи;
- построение плана;
- разбиение на блоки;
- генерация кода;
- самопроверка;
- подготовка отчета пользователю.

### Coordinator Review Gate

Обязательный контрольный слой.

Он проверяет каждый завершенный блок перед переходом дальше.

Проверяется:

- соответствует ли результат задаче;
- не нарушена ли архитектура;
- нет ли явных дыр в логике;
- не добавлен ли лишний функционал;
- не сломаны ли зависимости;
- можно ли переходить к следующему блоку.

### Tools Layer

Слой инструментов. На v0.1 может быть минимальным или ручным.

Возможные инструменты в будущем:

- чтение файлов;
- запись файлов;
- запуск тестов;
- поиск по проекту;
- локальный RAG;
- управляемый интернет-поиск;
- профили моделей.

### Memory / Project Context

Контекст проекта, который помогает VEGA помнить архитектуру и правила.

На v0.1 это могут быть markdown-файлы в папке `docs` и `prompts`.

Позже можно добавить RAG.

## 5. Интернет-режим

По умолчанию интернет должен быть выключен.

```text
Internet: OFF
```

Если позже будет добавлен интернет-доступ, он должен работать только явно:

```text
/search on
/search off
```

VEGA не должна сама незаметно ходить в интернет. Пользователь должен видеть режим.

## 6. Границы ответственности

VEGA может:

- писать код;
- объяснять архитектуру;
- проверять логику;
- предлагать структуру файлов;
- делать рефакторинг;
- создавать документацию;
- вести пользователя по этапам.

VEGA не должна:

- притворяться, что запустила код, если не запускала;
- делать вид, что проверила файлы, если не имеет доступа к ним;
- переходить к следующему блоку без review-gate;
- усложнять проект без причины;
- добавлять GUI раньше стабильной базы;
- соглашаться с плохой идеей только ради вежливости.

## Controlled coding workflow layer

VEGA v2.13.0 composes the existing deterministic workflow registry, Patch
Tools, Test Tools, permission policy, checkpoints, execution traces, doctor
diagnostics, and v2.12 state lock. It does not create a second registry or a
model-to-tool path.

```text
exact CLI or deterministic intent
    -> controlled WorkflowEngine
        -> bounded read-only investigation
        -> managed Patch Tools metadata
        -> PermissionEvaluator and exact patch binding
        -> Patch Tools apply once
        -> new exact test binding
        -> allowlisted Test Tools group once
        -> bounded outcome and archived state
```

The lifecycle, transition table, persistence contract, confirmation binding,
migration rules, threat model, and limitations are maintained in
[`docs/v2.13-architecture.md`](v2.13-architecture.md).

<!-- VEGA DOCGEN START: architecture -->
## Generated project snapshot

Project version: `v2.13.0`

This section is generated from the current project tree.

### Top-level directories

- `config/`
- `core/`
- `data/`
- `docs/`
- `domains/`
- `logs/`
- `memory/`
- `ollama/`
- `permissions/`
- `planner/`
- `plugins/`
- `prompts/`
- `rag/`
- `review/`
- `scripts/`
- `tests/`
- `tools/`
- `ui/`
- `web_demo/`
- `workflows/`

### Core modules

- `core/agent_modes.py`
- `core/command_handler.py`
- `core/contextual_runtime.py`
- `core/execution_trace.py`
- `core/internet_state.py`
- `core/model_router.py`
- `core/network_safety.py`
- `core/policy_consistency.py`
- `core/production_runtime.py`
- `core/production_snapshot.py`
- `core/review_gate.py`
- `core/safety.py`
- `core/task_manager.py`
- `core/task_state.py`

### Tool modules

- `tools/doc_builders.py`
- `tools/doc_tools.py`
- `tools/file_tools.py`
- `tools/git_tools.py`
- `tools/patch_tools.py`
- `tools/registry.py`
- `tools/release_tools.py`
- `tools/terminal_tools.py`
- `tools/test_tools.py`
- `tools/web_tools.py`

### Dependency direction

```text
scripts -> core -> tools -> policies and project data
```

Generated documentation changes are proposed through Patch Tools and are not applied automatically.
<!-- VEGA DOCGEN END: architecture -->

## Release Manager

The Release Manager is a read-only release-readiness layer.

```text
scripts/vega.py
    -> core/command_handler.py
        -> tools/release_tools.py
            -> config/release_policy.json
```

It checks release state but does not commit, tag, push, or publish releases.

## Agent Orchestration Foundation

The v2.0 runtime has a one-way dependency flow:

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

`scripts/vega.py` is the thin CLI entrypoint. `core/agent_runtime.py` owns the interactive session and invokes commands or Ollama after routing. `IntentRouter` classifies raw input, `CommandRouter` resolves explicit slash commands, `ExecutionContext` owns process-local session state, and `ConfirmationManager` permits at most one pending confirmation. `AgentOrchestrator` coordinates these components without executing commands or invoking the model. `ollama_client.py` contains the bounded local Ollama HTTP integration.

## Structured Command Execution

The v2.1 read-only command flow is:

```text
AgentOrchestrator
    -> CommandRoute
        -> CommandExecutionRequest
            -> CommandExecutor
                -> command handler
                    -> ToolExecutor
                        -> TOOL_REGISTRY
                            -> read-only tool
```

The runtime owns one `ToolExecutor` for the session and passes it through the command compatibility adapter. Only `/file`, `/git`, and `/tools list` use this tool-execution path. The model and orchestrator do not receive the executor.

## Coding Workflows

```text
IntentRouter -> CommandRouter -> WorkflowRegistry -> WorkflowEngine
    -> project context / planner -> Patch Tools -> confirmation -> Test Tools
```

`workflows/` owns models, transitions, persistence, ordered execution, and the
three coding definitions. Active state is written atomically; terminal runs move
from `data/workflows/active/` to `data/workflows/history/`.

`ProjectContextAdapter` reads the actual workspace tree, entrypoints, related
files, tests, documentation, active mode, and current Project Control Layer task.
`TaskSystemAdapter` stores the generated workflow plan through the existing
`TaskManager`; it is not a second task store. `TaskPlanner` remains separate
because `TaskManager` validates and persists user task plans but does not derive a
plan from workflow type, task text, and project context.

Every run persists structured `WorkflowStep` records and artifacts. Production
Patch and Test adapters fail closed. Recovery inspects persisted step results and
Patch Tools state so an applied patch is never applied twice.

## Permissions System

The v2.6 production execution flow is:

```text
CLI or runtime request
    -> ToolRequest
    -> ToolExecutor
    -> PermissionEvaluator
    -> allow / confirm / deny
    -> optional one-time confirmation or active session grant
    -> argument validation
    -> callable execution
    -> ToolExecutionResult
```

Production construction uses the fixed `TOOL_REGISTRY`, the fixed production
permission policy, and exact registry-policy alignment. One `SessionGrantStore`
is created for each VEGA process and the same store is shared by `ToolExecutor`
and `/permissions` commands.

`ToolExecutor(custom_registry)` without an evaluator retains isolated legacy
behavior. Partial test registries do not automatically load the production
policy. Background and non-interactive execution remain fail closed whenever a
production rule requires confirmation.

`core/confirmation_manager.py` owns workflow/orchestrator confirmation state.
`core/tool_confirmation.py` independently owns interactive tool-permission
confirmation; neither system substitutes for or grants state to the other.

## Plugin and Domain API

The v2.8 architecture adds metadata and trusted-module extension boundaries
without changing v2.7 intent planning:

```text
DomainRegistry
    -> PluginPolicy
        -> trusted-root and module-origin validation
            -> PluginLoader (collect manifests only)
                -> phase-one set and collision validation
                    -> permission/capability activation gate
                        -> immutable bootstrap result
                            -> build_plugin_tool_executor
                                -> ToolExecutor
                                    -> PermissionEvaluator
                                        -> callable handler
```

`DomainRegistry` validates all domain references before registration.
`PluginPolicy` is disabled by default and permits imports only when a normalized
dotted module is present in `allowed_modules` and matches an
`allowed_package_prefixes` entry. Enabled policies also require relative trusted
roots that resolve to existing directories inside the project root. The loader
resolves each dotted component independently with `PathFinder.find_spec` and an
explicit search path beginning at the project root and continuing through
validated parent package locations. It never uses global `sys.path` to select a
plugin chain. Only `SourceFileLoader` source modules and packages are accepted;
namespace, built-in, frozen, extension, sourceless, zip, custom-loader,
missing-loader, and out-of-root modules are rejected.

The complete chain is validated before execution. Under a process-local reentrant
lock, the resolver checks pre-existing `sys.modules` entries against the expected
`module.__spec__.origin`, `module.__file__`, and package `module.__path__`, then
executes only the previously validated specs with `module_from_spec` and
`exec_module`. Child attributes are attached to a parent only after post-exec
validation. On failure, only modules and attributes added by the current resolver
call are removed; pre-existing modules remain untouched. `PluginLoader` supports only
`get_plugin_manifest()` and returns a validated manifest without mutating a
registry.

Bootstrap first collects every manifest and validates limits, plugin names,
tool names, built-in collisions, and domains. Only after the whole set passes
does it create an internal registry and publish immutable manifest snapshots.
Import and factory side effects are not transactional and cannot be rolled
back. Resolver cleanup restores only its `sys.modules` and parent-attribute
publication, not filesystem, network, process, or other effects performed by
executed Python code.

Every loaded tool receives a stable activation record. Missing or denied
permission rules, disabled domains, absent capability entries, permission
mismatches, and capability mismatches leave the tool inactive and outside the
combined mapping. The built-in registry is a read-only view over a private
source; the v2.7 `TOOL_REGISTRY` remains a separate compatibility copy.

The supported production plugin execution path uses
`build_plugin_tool_executor`, which requires a `PermissionEvaluator` and returns
the existing `ToolExecutor`. The general Python API still permits trusted code
to call a handler or construct a legacy executor directly; this API does not
claim to prevent that outside the supported path.

The Plugin API is **not a security sandbox**. Python import executes module-level
code, so this is a controlled API for explicitly trusted local modules. The
allowlist and origin checks reduce accidental or ambiguous loading; they do not
make untrusted Python safe.

## v2.10 cross-layer reliability architecture

The implemented contract for the v2.10 stabilization release is documented in
[`docs/v2.10-architecture.md`](v2.10-architecture.md). Startup composes one
immutable production snapshot across routing, domains, capabilities, tools,
plugins, permissions, model profiles, and context budgets. Fatal drift blocks
normal tool publication; intentional nonautomatic routes are warnings.

Execution traces use request-local state and payload-free plan observations.
Persistence is disabled by default, writes allowlisted UTF-8 JSONL only when
explicitly enabled, and retains one bounded backup under a process-local lock.
Trace, serializer, callback, directory, append, and rotation failures cannot
alter execution results. Mutable profile/task state is untracked and ignored;
profile replacement is atomic. Stable failure codes and deterministic synthesis
fallbacks complete the v2.10 failure matrix without introducing a second tool
execution path.

## v2.11 runtime diagnostics architecture

The implemented v2.11 contract is documented in
[`docs/v2.11-architecture.md`](v2.11-architecture.md). One local observer builds
an immutable allowlisted report from the production snapshot and safe subsystem
counts. It never receives a `ToolExecutor`, invokes a handler, launches a model,
or changes execution, permissions, routing, synthesis, and results.

Validated policy confines trace/report paths and hard-bounds file bytes, backups,
scanned files and records, serialized report bytes, and retained reports. Trace
rotation retains three backups by default and valid v2.10 records remain
readable. `/doctor export` is explicit and atomic; no automatic or remote
telemetry exists.

## v2.12 local state integrity and recovery architecture

The implemented v2.12 contract is documented in
[`docs/v2.12-architecture.md`](v2.12-architecture.md). A dependency-free lock
layer coordinates trace and report mutations across VEGA processes with fixed
project-confined lock names and bounded acquisition. Windows uses byte-range
locking; POSIX uses advisory `flock`.

Read-only inspection classifies stale atomic-write files, incomplete JSONL tails,
complete corruption, and quarantine state under hard scan limits. Repair is
available only through the exact `/doctor state repair` command, rechecks state
under locks, preserves valid trace records, quarantines ambiguous generated
files, and never traverses arbitrary user paths. Diagnostics continue to observe
the existing `contextual runtime -> plan execution -> PlanExecutor ->
ToolExecutor` route without receiving tool authority.
