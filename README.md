# VEGA

VEGA is a local project coding-agent for working with code, project structure, local tasks, and local documents.

## Current version

v0.7.0

## Features

* Local CLI agent
* Ollama model support
* Project-focused coding assistant
* ASCII-only startup screen
* Session logs
* Task Console
* Documents / RAG commands
* Local document indexing
* Search over indexed documents
* Runtime status command
* Health-check script

## Requirements

* Windows
* Python 3.14+
* Ollama
* Local Ollama model: vega-core

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
/project
/log
/docs
/docs list
/docs index
/docs search <query>
/docs read <filename>
/task
/task new <title>
/task plan
/task step <text>
/task done <number>
/task note <text>
/task review
/task close
/task clear
/exit
/bye
/q
```

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

VEGA v0.7.0 can read local text documents, build a simple local index, and search it.

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
```

## Health check

Run:

```bat
python scripts\check_v033.py
```

Expected result:

```text
Result: OK
```

## Project status

Current stable checkpoint:

v0.7.0 - CLI agent with Task Console and local Document Reader / RAG.

Next planned stage:

```text
undecided
```
