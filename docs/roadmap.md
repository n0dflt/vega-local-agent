# Roadmap VEGA

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
