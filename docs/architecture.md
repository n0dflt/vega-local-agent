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

<!-- VEGA DOCGEN START: architecture -->
## Generated project snapshot

Project version: `v2.2.0`

This section is generated from the current project tree.

### Top-level directories

- `config/`
- `core/`
- `data/`
- `docs/`
- `logs/`
- `memory/`
- `ollama/`
- `planner/`
- `prompts/`
- `rag/`
- `scripts/`
- `tests/`
- `tools/`
- `ui/`
- `web_demo/`
- `workflows/`

### Core modules

- `core/agent_modes.py`
- `core/command_handler.py`
- `core/internet_state.py`
- `core/model_router.py`
- `core/network_safety.py`
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
