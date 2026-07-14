# VEGA v2.12.0 Release Notes

VEGA v2.12.0, **Local State Integrity & Recovery**, coordinates generated local
state across VEGA processes and provides an explicit bounded recovery path after
interrupted or corrupted writes.

## Highlights

* Standard-library Windows and POSIX interprocess locks protect trace append,
  rotation, diagnostic export, and report retention.
* `/doctor state status` is an exact read-only integrity command.
* `/doctor state repair` is the only explicit state mutation command and accepts
  no arguments or paths.
* Torn JSONL tails are recovered while earlier valid records are preserved;
  complete corruption is quarantined.
* Recognized stale atomic-write files and quarantine retention are cleaned under
  strict work and traversal limits.
* Immutable manually serialized diagnostics expose only allowlisted metadata and
  fixed safe codes.

## Coordination and persistence

Fixed `.trace-state.lock` and `.report-state.lock` files live inside validated
generated-state directories. Acquisition is non-blocking with a strict timeout
capped at five seconds. Windows uses byte-range locks and POSIX uses advisory
`flock`; process-local synchronization remains in place. Context cleanup and OS
process exit release locks, including failure-injection and abandoned-process
cases.

Trace records and reports flush and `fsync`. Reports retain same-directory temp
creation and atomic replacement. Trace rotation now permits a file to reach its
configured ceiling exactly and rotates before another record would exceed it.
Persistence failures remain best effort and cannot alter tool, plan, or normal
user results.

## Explicit recovery

`/doctor state status` does not create directories or lock files. It reports only
lock availability, stale-temp count, torn-tail state, corrupt-file count,
quarantine count, relative paths, scan state, and fixed codes.

`/doctor state repair` rechecks generated state under locks in fixed order. It
normalizes a valid final JSONL record missing a newline, removes an invalid
incomplete final fragment, quarantines newline-terminated corruption before
atomically restoring valid records, atomically confines oversized traces without
reading their payload, and deletes only exact stale temp names. Repeated repair
is safe and bounded.

Unknown, fuzzy, differently cased, extra-whitespace, additional-argument,
absolute-path, and relative-path variants do not mutate the filesystem.

## Security boundaries

Policy schema version 2 rejects unknown, missing, duplicate, incorrectly typed,
boolean-as-integer, zero/negative, above-cap, absolute, drive-qualified,
traversing, blocked, and symlink-escaping values. Runtime use rechecks directory
and lock-file symlinks. Repair never recurses or accepts an arbitrary path.

Doctor output and serialized reports exclude prompts, user content, evidence,
payloads, tool arguments/results, command output, exceptions, tracebacks,
absolute user paths, environment values, tokens, credentials, callbacks, and
arbitrary representations. Diagnostics remain observer-only and do not gain a
tool, model, network, telemetry, autonomous repair, or publication path.

## Compatibility and migration

Existing public trace APIs and the v2.10/v2.11 trace record shape are unchanged.
Valid old active and backup traces remain readable. Trace persistence remains
opt-in with `VEGA_EXECUTION_TRACE`. No generated-state migration is automatic;
projects adopt the supplied diagnostics policy schema version 2.

Rollback to v2.11 requires restoring its diagnostics policy schema. Valid traces
remain compatible. Lock and quarantine files are ignored by Git and can be left
in place; stop all VEGA processes before manual cleanup.

## Validation

The release gate includes focused multiprocessing, contention, adapter,
failure-injection, rotation, interrupted-write, recovery, quarantine, path,
limit, command, sentinel, compatibility, release identity, and documentation
tests; the full suite; compileall; identity and production policy consistency;
smoke tests; built-in Release Manager; Git whitespace and generated-state checks;
and all GitHub CI checks.

Local release-gate results on Windows:

* focused v2.12/release tests: `106 passed, 2 skipped`;
* full suite: `1126 test results, 0 failures, 0 errors, 5 skipped`;
* compileall, identity, production policy consistency, smoke test, Release
  Manager, working/staged whitespace, and generated-state tracking: passed.

All five full-suite skips require Windows symlink privileges unavailable in the
validation environment; four predate v2.12 and the new state-integrity symlink
test uses the same conditional coverage. The two production-policy warnings are
the intentional nonautomatic `bug_fix` and `test_run` routes retained from
v2.10/v2.11.

## Known limitations

* Locks are advisory and cannot coordinate unrelated programs that ignore them.
* Recovery is bounded rather than forensic and fails closed at hard limits.
* Trace persistence remains opt-in and reports remain local-only.
* There is no startup repair, background monitor, remote telemetry, upload,
  autonomous execution, or application-level automatic publishing.
