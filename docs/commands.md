# VEGA commands

## /file commands

```text
/file
/file list <path>
/file read <path>
/file find <name>
/file search <query>
/file summary <path>
```

The file commands provide safe, read-only access inside the VEGA project root. They
block path traversal, service directories, sensitive files, keys, certificates, and
binary content. Use `/tools list` to display registered tools.


## /patch commands

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

`/patch propose` creates a pending patch without changing the target file.

`/patch apply` requires the exact `CONFIRM` token. VEGA verifies SHA-256 before
applying the patch, blocks stale patches, and creates an exact byte-level backup.

`/patch rollback` also requires `CONFIRM` and restores the original bytes.

Path traversal, sensitive files, service directories, and identical target and
proposal paths are blocked.

## /git commands

Safe read-only Git access:

```text
/git
/git status
/git diff
/git diff --cached
/git log
/git log <limit>
/git branch
```

`/git status` shows the short repository status.

`/git diff` shows unstaged changes. `/git diff --cached` shows staged changes.

`/git log` shows 10 recent commits by default. The optional limit must be an integer from 1 to 100.

`/git branch` shows the current branch.

Git Tools in v1.4.0 are read-only. Commit, tag, push, pull, checkout, reset, merge, rebase, configuration changes, and arbitrary Git command execution are unavailable.

<!-- VEGA DOCGEN START: commands -->
## Generated command reference

Project version: `v1.10.0`

This section is generated from `scripts/vega.py`.

### Available command roots

```text
/about
/workspace
/task
/journal
/project
/help
/status
/doctor
/model
/docs
/file
/tools
/run
/test
/internet
/web
/docgen
/exit
/patch
/git
/memory
/log
/clear
```

### CLI help entries

```text
/about                  Show VEGA release information.
/help                   Show this help.
/status                 Show VEGA runtime status.
/doctor                 Run project diagnostics.
/model                  Show current model profile.
/model status           Show Ollama/model status.
/model install-help     Show recommended install commands.
/docs                   Show documents help.
/docs list              Show documents.
/docs index             Rebuild local document index.
/docs search <query>    Search indexed documents.
/docs read <filename>   Read a local document.
/docs analyze <file>    Analyze a local document.
/docs summarize <file>  Summarize a local document.
/docs ask <question>    Ask indexed documents.
/file                  Show safe file command help.
/patch                 Show safe patch command help.
/git                   Show safe Git command help.
/tools list            Show registered tools.
/memory                Show Project Memory help.
/memory add ...        Save a project decision, fact, or constraint.
/memory list [kind]    List saved project memory.
/memory search <query> Search saved project memory.
/memory stats          Show Project Memory statistics.
/run                   Show Safe Terminal Tools help.
/run list              List predefined validation commands.
/run <command-id>      Run one predefined validation command.
/test                  Run all VEGA tests.
/test list             List predefined test groups.
/test <group-id>       Run one predefined test group.
/internet              Show current internet state.
/internet on           Enable internet for this VEGA process.
/internet off          Disable internet for this VEGA process.
/web fetch <https-url> Fetch one bounded text resource.
/docgen                Show Documentation Builder help.
/docgen status         Show project documentation status.
/docgen check          Check required project documentation.
/docgen build          Create pending documentation patches.
/workspace              Show workspace state
/task                   Show task command help
/exit                   Exit VEGA
/model fast | /model code | /model docs | /model deep
/project | /project status | /log | /clear
```
<!-- VEGA DOCGEN END: commands -->
