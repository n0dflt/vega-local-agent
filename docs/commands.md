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

## /doctor commands

```text
/doctor
/doctor help
/doctor trace status
/doctor trace latest
/doctor trace summary
/doctor state status
/doctor state repair
/doctor export
```

`/doctor` shows a compact payload-free runtime summary. Trace commands read only
the bounded local trace store. `/doctor state status` is read-only and reports
only allowlisted metadata. `/doctor state repair` accepts no arguments and is the
only repair path; it mutates only recognized generated VEGA state under bounded
locks. `/doctor export` is the only command that creates a report; it accepts no
path argument and prints a relative path such as:

```text
Diagnostics report exported: logs/diagnostics/reports/doctor-20260714T120000000000Z.json
```

Unknown subcommands and extra export arguments show usage and do not create a
file. No doctor output includes an absolute project path.

<!-- VEGA DOCGEN START: commands -->
## Generated command reference

Project version: `v2.12.0`

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
/release
/workflow
/exit
/patch
/git
/memory
/mode
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
/mode                  Show the active agent mode.
/mode list             List available agent modes.
/mode set <name>       Activate an agent mode.
/mode reset            Restore the default agent mode.
/docgen                Show Documentation Builder help.
/docgen status         Show project documentation status.
/docgen check          Check required project documentation.
/docgen build          Create pending documentation patches.
/release                Show Release Manager help.
/release status         Show release readiness.
/release check          Run configured release checks.
/release notes          Build release notes draft.
/workflow              Show Coding Workflow help.
/workflow start ...    Start feature, bugfix, or refactor workflow.
/workspace              Show workspace state
/task                   Show task command help
/exit                   Exit VEGA
/model fast | /model code | /model docs | /model deep
/project | /project status | /log | /clear
```
<!-- VEGA DOCGEN END: commands -->

## Release Manager commands

```text
/release
/release status
/release check
/release notes
```

`/release check` runs only validation commands allowed by the release policy.

## v2.0 command routing

User input is classified by `IntentRouter`. Explicit slash commands are then resolved deterministically by `CommandRouter` before the runtime invokes an existing command handler. Slash commands remain explicit user input; ordinary chat text cannot be promoted to a command by the model.

## v2.1 structured command execution

Routed slash commands are wrapped in `CommandExecutionRequest` and executed through `CommandExecutor`. Handlers retain explicit parsing and output behavior.

Read-only command-to-tool mappings are fixed in code:

```text
/file list       -> list_dir
/file read       -> read_file
/file find       -> find_file
/file search     -> search_in_files
/file summary    -> summarize_file
/file summarize  -> summarize_file

/git status         -> git_status
/git diff           -> git_diff
/git diff --cached  -> git_diff_cached
/git log            -> git_log
/git branch         -> git_branch

/tools list -> ToolExecutor.registered_tools
```

There is no `/tools run` command and no user-controlled registered tool name.

## v2.2 coding workflow commands

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

Start analyzes and plans the task without writes, persists the draft, and stops at
`waiting_patch`. `attach-patch` validates a pending artifact and stops at
`waiting_confirmation`. Only `/workflow confirm` applies it. `link-task` is the
only workflow command allowed to copy the workflow plan into an existing task.

## v2.6 permission commands

```text
/permissions
/permissions grants
/permissions revoke <tool_name>
/permissions clear
```

`/permissions` shows help, `grants` lists active process-local grants, `revoke`
removes the grant for one exact tool, and `clear` removes every active grant.
There is no `/permissions grant <tool_name>` command. A session grant can only
originate from a real confirmation-required tool invocation and an explicit
session approval when production policy permits it.

For one-time prompts, `y` and `yes` approve the current invocation; `n`, `no`,
empty or unknown input, EOF, `KeyboardInterrupt`, and callback errors reject or
cancel it. Non-interactive confirmation-required commands remain blocked. The
internal confirmation token is not displayed, and confirmation metadata is not
passed to tool callables.
