\# VEGA Security



\## Security model



VEGA is a local project coding-agent with controlled access to files,

commands, Git, tests, project memory, and the internet.



Tools must use explicit policies and remain inside the project workspace.



\## File access



File Tools provide read-only access to project files.



Blocked operations and targets include:



\- paths outside the project root;

\- parent-directory traversal;

\- service directories such as `.git` and `\_\_pycache\_\_`;

\- environment files;

\- credentials, tokens, passwords, and private keys;

\- binary files;

\- symbolic links used for writable paths.



\## File modifications



Project files must not be modified silently.



Changes are prepared through Patch Tools:



```text

/patch propose <target> <proposal> \[reason]

/patch show <patch\_id>

/patch apply <patch\_id> CONFIRM

/patch rollback <patch\_id> CONFIRM

## Agent Mode enforcement

VEGA Agent Modes are process-local execution policies.

Modes with `allow_code_changes: false` block:

* `/patch apply <patch_id> CONFIRM`
* `/patch rollback <patch_id> CONFIRM`

The restriction applies to:

* `architect`
* `reviewer`
* `teacher`
* `release_manager`

The `coder` and `debugger` modes may perform confirmed patch operations. The exact
`CONFIRM` token, SHA-256 validation, workspace restrictions, and Patch Tools safety
checks remain mandatory in every mode.

Mode instructions added to the model context do not replace command-level safety
enforcement.

<!-- VEGA DOCGEN START: security -->
## Generated security snapshot

Project version: `v2.10.0`

### Documentation Builder policy

- Create missing files automatically: `false`
- Use Patch Tools: `true`
- Apply patches automatically: `false`
- Require confirmation token: `true`

### Limits

- Maximum document characters: `100000`
- Maximum generated documents: `10`

### Active policy files

- `config/allowed_commands.json`
- `config/internet_policy.json`
- `config/documentation_policy.json`
- `config/release_policy.json`

### Enforcement principles

1. Documentation targets must remain inside the project root.
2. Missing managed files are not created automatically.
3. Generated changes become pending patches.
4. Pending patches are never applied by `/docgen build`.
5. Patch application requires a separate explicit command.
<!-- VEGA DOCGEN END: security -->

## Release Manager security

* Release Manager is read-only.
* Automatic commits are disabled.
* Automatic tags are disabled.
* Automatic pushes are disabled.
* Automatic GitHub releases are disabled.
* Validation commands must be predefined.
* Release paths cannot escape the project root.

## Agent Orchestrator security

* Input and slash-command routing are deterministic.
* The model cannot turn ordinary chat text into a command.
* Automatic model-driven tool execution is disabled.
* The orchestrator grants no additional filesystem, shell, Git, or network permissions.
* Existing workspace, terminal, internet, patch, confirmation, and Git policies remain authoritative.

## Controlled Tool Orchestration security

* Command handlers select tool names from fixed mappings; arbitrary tool names are rejected by design.
* The model does not invoke tools and does not receive `ToolExecutor`.
* `AgentOrchestrator` routes input but does not receive or execute tools.
* `ToolExecutor` is connected only to `/file`, `/git`, and `/tools list`.
* Automatic model-driven tool calling and autonomous execution loops remain disabled.
* Existing write, terminal, test, internet, web, patch, and confirmation paths retain their established policies.

## Tool permissions

VEGA v2.6 enforces permission effects `allow`, `confirm`, and `deny`; risk labels are `low`,
`medium`, `high`, and `critical`. `allow` executes normally, `confirm` requires
explicit approval, and `deny` never executes. Missing rules and evaluator errors
fail closed. Unknown registry names still report `unknown_tool`, and confirmation
metadata is never passed to tool callables.

The current production policy explicitly allows:

* `documentation_check`, `documentation_policy_load`, `documentation_status`;
* `find_file`, `list_dir`, `read_file`, `search_in_files`, `summarize_file`;
* `git_branch`, `git_diff`, `git_diff_cached`, `git_log`, `git_status`;
* `internet_status`, `list_patches`, `memory_list`, `memory_search`,
  `memory_stats`, `release_notes`, `release_policy_load`, `release_status`,
  `show_patch`, `terminal_list`, and `test_list`.

The current production policy requires confirmation for `apply_patch`,
`documentation_build`, `internet_set`, `memory_add`, `propose_patch`,
`propose_patch_from_file`, `release_check`, `rollback_patch`, `terminal_run`,
`test_run`, and `web_fetch`. There are no explicit production `deny` rules;
unclassified tools are denied by the fail-closed default.

Session approval is available only for `memory_add`, `propose_patch`, and
`propose_patch_from_file`. It is explicitly unavailable for `apply_patch`,
`documentation_build`, `internet_set`, `release_check`, `rollback_patch`,
`terminal_run`, `test_run`, and `web_fetch`.

Session grants live only in memory for the current VEGA process, start empty, and
apply to one exact tool. They are never persisted or stored in checkpoints,
workflows, project memory, configuration, or logs. They cannot cross processes,
and production policy is rechecked before every use.

One-time input `y` or `yes` approves once. `n` or `no`, empty and unknown input,
EOF, `KeyboardInterrupt`, callback errors, and unavailable interactive input all
fail closed. The internal confirmation token is not shown to the user.
