# Changelog

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
