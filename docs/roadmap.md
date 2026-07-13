# Roadmap VEGA

## Current project status

Current stable release:

```text
v2.7.2 - UTF-8 Documentation Fix
```

Latest functional release:

```text
v2.7.0 - Context-Aware Tool Orchestration
```

Previous documentation and licensing release:

```text
v2.7.1 - Documentation and Licensing Patch
```

Next planned release:

```text
v2.8.0 - Plugin and Domain API
```

The v2.7.2 hotfix restores valid UTF-8 documentation after the v2.7.1
PowerShell editing process corrupted Cyrillic text. Runtime behavior,
permissions, workflows, tool routing, and execution policies are unchanged.

## v0.1 — стабильная база

Цель: сделать минимального, но понятного локального агента.

Что входит:

- имя VEGA;
- базовый system prompt;
- CLI-баннер;
- статусы сообщений;
- architecture docs;
- Coordinator Review Gate;
- ручной контроль пользователя;
- понятные ограничения.

Что не входит:

- GUI;
- сложная автономность;
- полноценный RAG;
- автоматический интернет;
- много моделей сразу.

## v0.2 — проектный coding-agent

Цель: VEGA лучше работает с проектами.

Добавить:

- структуру задач;
- работу по блокам;
- шаблон анализа кода;
- шаблон рефакторинга;
- шаблон bugfix;
- базовую проверку файлов;
- запуск тестов, если tools доступны.

## v0.3 — документы и RAG

Цель: VEGA использует проектные документы как память.

Добавить:

- локальную базу документов;
- поиск по markdown-файлам;
- подключение архитектурных инструкций;
- ответы с учетом проектного контекста;
- защиту от устаревших инструкций.

## v0.4 — профили моделей

Цель: разные модели под разные задачи.

Примеры профилей:

- coding;
- architecture;
- review;
- documentation;
- lightweight chat.

## v0.5 — GUI или расширенный интерфейс

Цель: улучшить удобство после стабильной базы.

Возможные варианты:

- TUI в терминале;
- web-интерфейс;
- desktop GUI;
- панель статусов;
- история задач;
- визуальный task board.

## Критический принцип roadmap

Не добавлять красивый интерфейс раньше стабильной логики агента.

Сначала процесс. Потом инструменты. Потом внешний вид.

## v2.0.0 release status

Status: `completed`

## v2.1.0 release status

Status: `completed`

Completed scope:

* `CommandExecutor` and structured command results.
* `ToolExecutor` and controlled registered-tool invocation.
* Runtime integration through compatibility adapters.
* Read-only command integration for `/file`, `/git`, and `/tools list`.

## v2.2.0 release status

Status: `implementation complete, pending release review`

Implemented scope:

* Persistent feature, bugfix, and refactor workflows.
* Explicit confirmation before patch application.
* Active/history storage, resume, cancellation, and final reports.
* Deterministic `/workflow` command routing.

Next stage: `v2.3.0 — Controlled Test–Fix Loop`.

## v2.6.0 release status

Status: `release prepared`

Completed scope:

* Fail-closed production permission policy and exact registry alignment.
* Runtime `ToolExecutor` permission enforcement.
* One-time tool confirmation and policy-limited process-local session grants.
* `/permissions` grant lifecycle inspection and revocation commands.

## v2.7.0 release status

Status: `release prepared`

Completed scope:

* Deterministic intent analysis and task interpretation.
* Capability-based planning with safe argument binding.
* Contextual preview and controlled tool execution.
* Evidence-backed synthesis for supported completed reads.

Next stage: `v2.8.0 - Plugin and Domain API`.

## v2.8.0 release status

Status: `implementation in progress`

Implemented scope:

* Immutable domain definitions and deterministic domain registration.
* Built-in coding and research domain metadata.
* Strict plugin manifests and validation.
* Fail-closed allowlists, trusted roots, and component-by-component `PathFinder`
  provenance validation before source-module execution.
* Two-phase manifest collection and immutable bootstrap result models.
* Loaded/inactive/active tool state with permission and capability gates.
* Isolated combined tool registry construction.
* A supported runtime factory requiring the existing `PermissionEvaluator` and
  returning the existing `ToolExecutor`.

Not included:

* Plugin marketplace.
* Installation from GitHub or PyPI.
* File-path plugin loading.
* Python entry-point discovery.
* Hot reload.
* Automatic permission-policy modification.
* Automatic contextual-routing metadata modification.

Known limitation:

* Python module import and plugin factory side effects cannot be rolled back;
  the Plugin API is not a sandbox and is limited to explicitly trusted code.
  Resolver cleanup is limited to modules and parent attributes published by the
  failing resolver call.
