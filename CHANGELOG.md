# Changelog

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

