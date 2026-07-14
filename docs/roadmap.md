# Roadmap VEGA

## Current project status

Current stable release:

```text
v2.12.1 - Local State Integrity & Recovery Stabilization
```

Previous stable release:

```text
v2.11.0 - Runtime Diagnostics Evolution
```

Previous extension API release:

```text
v2.8.0 - Plugin and Domain API
```

Next planned release:

```text
TBD
```

v2.12 is implemented and release-validated. It adds bounded cross-process local
state coordination and explicit recovery without autonomous execution, remote
telemetry, background monitoring, or a new tool path.

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

Status: `completed in v2.8.0`

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

## v2.9.0 implementation baseline

Implemented in tag `v2.9.0`:

* deterministic model profile selection and installed-model fallback;
* intent-based automatic selection with manual profile preservation;
* per-profile context budgets; and
* bounded evidence synthesis with deterministic fallback.

The v2.9 tag remains the model/context baseline consumed by v2.10.

## v2.10.0 release status

Status: `implemented and release-validated`

Implemented in `feature/v2.10-runtime-snapshot-gate`:

* one immutable validated production snapshot for routing metadata, permission
  policy, built-in/plugin tool mapping, contextual catalog, and executor;
* fail-closed bootstrap that publishes no normal handlers after a fatal policy
  issue or executor-construction failure; and
* safe blocked execution plus focused integration and regression coverage.

Implemented in `feature/v2.10-execution-traces`:

* immutable execution traces containing only allowlisted machine decisions;
* bounded identifiers, steps, serialization, active file, and one backup;
* opt-in UTF-8 JSONL persistence, disabled by default;
* payload-free contextual and plan-execution hooks; and
* safe `/doctor` trace availability and latest-summary diagnostics.

Completed stabilization scope:

* cross-layer validation of intents, domains, capabilities, tools, plugins,
  permissions, model profiles, budgets, and policy schema versions;
* Git-safe ownership of mutable runtime state;
* deterministic model and synthesis failure paths;
* end-to-end routing, failure, plugin, and release regression tests; and
* synchronized v2.10 release identity and documentation.

The executable design and acceptance criteria are in
[`docs/v2.10-architecture.md`](v2.10-architecture.md). v2.10 does not add GUI,
monitoring, autonomous tool execution, a marketplace, or automatic publishing.
Confirmation-only `bug_fix` and `test_run` routes remain intentionally outside
the automatic contextual catalog and are reported as nonblocking warnings.

## v2.11.0 release status

Status: `implemented and release-validated`

Implemented in `feature/v2.11-runtime-diagnostics`:

* strict bounded diagnostics policy;
* immutable payload-free runtime reports;
* explicit atomic `/doctor export` and bounded report retention;
* `/doctor trace status`, compatible latest summary, and bounded aggregate;
* configurable three-backup trace rotation and active/backup scanning; and
* v2.10 trace compatibility, security regressions, and synchronized release
  identity.

See [`docs/v2.11-architecture.md`](v2.11-architecture.md). The next release scope
was v2.12 local-state integrity and recovery.

## v2.12.0 release status

Status: `implemented and release-validated`

Implemented in `feature/v2.12-state-integrity-recovery`:

* bounded Windows and POSIX interprocess state locks;
* crash-safe trace/report persistence coordination;
* read-only `/doctor state status` and explicit `/doctor state repair`;
* torn-tail recovery, complete-corruption quarantine, stale-temp cleanup, and
  bounded quarantine retention;
* diagnostics policy schema version 2 and immutable local-state reporting; and
* v2.10/v2.11 trace compatibility plus concurrency, security, and release
  regressions.

See [`docs/v2.12-architecture.md`](v2.12-architecture.md). The next release scope
is `TBD`.

## v2.12.1 stabilization status

Status: `implemented and release-validated`

The patch release fixes clean-checkout validation, hardens lock descriptors,
bounded reads, report classification, quarantine substitution, and failure-code
accuracy, and establishes Windows/Linux CI for Python 3.12–3.14. Product
execution and trace APIs remain unchanged. v2.13 Controlled Coding Workflows is
the next release scope.
