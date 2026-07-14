from __future__ import annotations

import json
import multiprocessing
import os
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.agent_runtime import handle_doctor_command
from core.execution_trace import (
    MAX_TRACE_CHARS,
    ExecutionTrace,
    TraceStatus,
    append_trace,
    scan_trace_store,
    serialize_trace,
)
from core.runtime_diagnostics import DiagnosticsPolicy
from core.state_integrity import (
    CORRUPT_GENERATED_STATE,
    MAX_LOCK_TIMEOUT_MS,
    RECOVERED_TORN_TRACE_TAIL,
    STATE_LOCK_OPERATION_FAILED,
    STATE_LOCK_TIMEOUT,
    STATE_SCAN_LIMIT_REACHED,
    GeneratedStateLock,
    PosixLockAdapter,
    StateIntegrityDiagnostics,
    StateLockError,
    WindowsLockAdapter,
    format_state_status,
    inspect_local_state,
    repair_local_state,
)


def _trace(identifier: str = "trace") -> ExecutionTrace:
    return ExecutionTrace(identifier, "contextual", status=TraceStatus.COMPLETED)


def _policy(root: Path, **changes: object) -> DiagnosticsPolicy:
    return replace(DiagnosticsPolicy.defaults(root), **changes)


def _write_policy(root: Path, **changes: object) -> DiagnosticsPolicy:
    policy = _policy(root, **changes)
    path = root / "config" / "diagnostics_policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": policy.schema_version,
                "trace_store_path": policy.trace_store_path,
                "max_trace_file_bytes": policy.max_trace_file_bytes,
                "retained_trace_backups": policy.retained_trace_backups,
                "max_trace_scan_files": policy.max_trace_scan_files,
                "max_trace_records": policy.max_trace_records,
                "doctor_reports_dir": policy.doctor_reports_dir,
                "max_doctor_report_bytes": policy.max_doctor_report_bytes,
                "retained_doctor_reports": policy.retained_doctor_reports,
                "lock_timeout_ms": policy.lock_timeout_ms,
                "stale_temp_age_seconds": policy.stale_temp_age_seconds,
                "max_state_scan_files": policy.max_state_scan_files,
                "retained_quarantine_files": policy.retained_quarantine_files,
            }
        ),
        encoding="utf-8",
    )
    return policy


def _writer(root: str, start: int, count: int, result: multiprocessing.Queue) -> None:
    os.environ["VEGA_EXECUTION_TRACE"] = "1"
    project = Path(root)
    policy = _policy(project, lock_timeout_ms=2_000, max_trace_records=256)
    written = 0
    for index in range(start, start + count):
        if append_trace(project, _trace(f"worker-{index}"), policy) is not None:
            written += 1
    result.put(written)


def _contended_writer(root: str, result: multiprocessing.Queue) -> None:
    os.environ["VEGA_EXECUTION_TRACE"] = "1"
    project = Path(root)
    policy = _policy(project, lock_timeout_ms=100)
    result.put(append_trace(project, _trace("contended"), policy) is not None)


def _rotating_writer(root: str, start: int, result: multiprocessing.Queue) -> None:
    os.environ["VEGA_EXECUTION_TRACE"] = "1"
    project = Path(root)
    policy = _policy(
        project,
        lock_timeout_ms=2_000,
        max_trace_file_bytes=1024,
        retained_trace_backups=3,
        max_trace_scan_files=4,
    )
    result.put(
        sum(
            append_trace(project, _trace(f"rotation-{start + index}"), policy)
            is not None
            for index in range(10)
        )
    )


def _abandon_lock(root: str) -> None:
    project = Path(root)
    directory = project / "logs" / "diagnostics"
    # Intentionally omit release; normal process termination must drop the OS lock.
    GeneratedStateLock(project, directory, "trace", 1_000).acquire()


def _spawn_context() -> multiprocessing.context.BaseContext:
    return multiprocessing.get_context("spawn")


def test_multiple_processes_append_complete_trace_records(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    context = _spawn_context()
    result = context.Queue()
    processes = [
        context.Process(target=_writer, args=(str(tmp_path), index * 15, 15, result))
        for index in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0

    assert sum(result.get(timeout=2) for _ in processes) == 60
    scan = scan_trace_store(tmp_path, _policy(tmp_path, max_trace_records=256))
    assert len(scan.traces) == 60
    assert scan.invalid_records == 0


def test_cross_process_contention_times_out_without_partial_append(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    policy = _policy(tmp_path, lock_timeout_ms=100)
    directory = tmp_path / Path(policy.trace_store_path).parent
    context = _spawn_context()
    result = context.Queue()

    with GeneratedStateLock(tmp_path, directory, "trace", 1_000):
        process = context.Process(target=_contended_writer, args=(str(tmp_path), result))
        process.start()
        process.join(5)
        assert process.exitcode == 0
        assert result.get(timeout=2) is False

    assert not (tmp_path / policy.trace_store_path).exists()


def test_abandoned_process_lock_is_released_by_operating_system(tmp_path: Path) -> None:
    context = _spawn_context()
    process = context.Process(target=_abandon_lock, args=(str(tmp_path),))
    process.start()
    process.join(5)
    assert process.exitcode == 0

    directory = tmp_path / "logs" / "diagnostics"
    with GeneratedStateLock(tmp_path, directory, "trace", 500):
        assert True


def test_lock_releases_after_protected_operation_exception(tmp_path: Path) -> None:
    directory = tmp_path / "logs" / "diagnostics"
    with pytest.raises(RuntimeError, match="injected"):
        with GeneratedStateLock(tmp_path, directory, "trace", 500):
            raise RuntimeError("injected")
    with GeneratedStateLock(tmp_path, directory, "trace", 500):
        assert True


class _FailingAdapter:
    def acquire(self, stream: object) -> None:
        raise OSError("TOP-SECRET-LOCK")

    def release(self, stream: object) -> None:
        raise AssertionError("unreachable")


class _ReleaseFailingAdapter:
    def acquire(self, stream: object) -> None:
        return None

    def release(self, stream: object) -> None:
        raise OSError("TOP-SECRET-RELEASE")


def test_lock_failure_injection_has_fixed_code_and_no_deadlock(tmp_path: Path) -> None:
    directory = tmp_path / "logs" / "diagnostics"
    with pytest.raises(StateLockError) as captured:
        GeneratedStateLock(
            tmp_path, directory, "trace", 50, adapter=_FailingAdapter()
        ).acquire()
    assert captured.value.code == STATE_LOCK_OPERATION_FAILED
    assert "TOP-SECRET" not in str(captured.value)
    with GeneratedStateLock(tmp_path, directory, "trace", 500):
        assert True


def test_release_failure_still_releases_process_lock(tmp_path: Path) -> None:
    directory = tmp_path / "logs" / "diagnostics"
    lock = GeneratedStateLock(
        tmp_path, directory, "trace", 50, adapter=_ReleaseFailingAdapter()
    )
    lock.acquire()
    with pytest.raises(StateLockError) as captured:
        lock.release()
    assert captured.value.code == STATE_LOCK_OPERATION_FAILED
    with GeneratedStateLock(tmp_path, directory, "trace", 500):
        assert True


def test_fixed_lock_scope_and_timeout_bounds_reject_unsafe_inputs(tmp_path: Path) -> None:
    with pytest.raises(StateLockError):
        GeneratedStateLock(tmp_path, tmp_path.parent, "trace", 10)
    with pytest.raises(StateLockError):
        GeneratedStateLock(tmp_path, tmp_path / "logs", "../../secret", 10)
    with pytest.raises(StateLockError):
        GeneratedStateLock(
            tmp_path, tmp_path / "logs", "trace", MAX_LOCK_TIMEOUT_MS + 1
        )


def test_symlinked_lock_file_and_generated_directory_fail_closed(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir(exist_ok=True)
    directory = tmp_path / "logs" / "diagnostics"
    directory.mkdir(parents=True)
    external_lock = outside / "lock"
    external_lock.write_bytes(b"0")
    lock_path = directory / ".trace-state.lock"
    try:
        lock_path.symlink_to(external_lock)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks are unavailable")

    with pytest.raises(StateLockError):
        GeneratedStateLock(tmp_path, directory, "trace", 50).acquire()
    assert external_lock.read_bytes() == b"0"

    lock_path.unlink()
    directory.rmdir()
    (tmp_path / "logs").rmdir()
    try:
        (tmp_path / "logs").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    status = inspect_local_state(tmp_path, _policy(tmp_path))
    assert not status.lock_available
    assert not (outside / ".trace-state.lock").exists()


def test_windows_adapter_uses_nonblocking_byte_range_lock(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[int, int]] = []
    fake = SimpleNamespace(
        LK_NBLCK=1,
        LK_UNLCK=2,
        locking=lambda descriptor, mode, count: calls.append((mode, count)),
    )
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    with (tmp_path / "lock").open("w+b") as stream:
        stream.write(b"0")
        WindowsLockAdapter().acquire(stream)
        WindowsLockAdapter().release(stream)
    assert calls == [(1, 1), (2, 1)]


def test_posix_adapter_uses_nonblocking_advisory_lock(monkeypatch, tmp_path: Path) -> None:
    calls: list[int] = []
    fake = SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lambda descriptor, operation: calls.append(operation),
    )
    monkeypatch.setitem(sys.modules, "fcntl", fake)
    with (tmp_path / "lock").open("w+b") as stream:
        PosixLockAdapter().acquire(stream)
        PosixLockAdapter().release(stream)
    assert calls == [3, 4]


def test_trace_rotation_allows_exact_threshold_then_rotates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    record = (serialize_trace(_trace("threshold")) + "\n").encode("utf-8")
    policy = _policy(
        tmp_path,
        max_trace_file_bytes=1024,
        retained_trace_backups=1,
        max_trace_scan_files=2,
    )
    path = tmp_path / policy.trace_store_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * (policy.max_trace_file_bytes - len(record)))

    assert append_trace(tmp_path, _trace("threshold"), policy) == path
    assert path.stat().st_size == policy.max_trace_file_bytes
    assert not path.with_name(path.name + ".1").exists()

    assert append_trace(tmp_path, _trace("rotated"), policy) == path
    assert path.with_name(path.name + ".1").stat().st_size == policy.max_trace_file_bytes


def test_trace_rotation_remains_bounded_under_process_contention(tmp_path: Path) -> None:
    context = _spawn_context()
    result = context.Queue()
    processes = [
        context.Process(target=_rotating_writer, args=(str(tmp_path), index * 10, result))
        for index in range(3)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    assert sum(result.get(timeout=2) for _ in processes) == 30

    policy = _policy(
        tmp_path,
        max_trace_file_bytes=1024,
        retained_trace_backups=3,
        max_trace_scan_files=4,
    )
    active = tmp_path / policy.trace_store_path
    paths = [active] + [active.with_name(f"{active.name}.{index}") for index in range(1, 4)]
    assert all(path.stat().st_size <= 1024 for path in paths if path.exists())
    assert scan_trace_store(tmp_path, policy).invalid_records == 0


def test_stale_report_temp_is_detected_and_explicitly_removed(tmp_path: Path) -> None:
    policy = _policy(tmp_path, stale_temp_age_seconds=60)
    reports = tmp_path / policy.doctor_reports_dir
    reports.mkdir(parents=True)
    stale = reports / ".doctor-20260714T000000000000Z.json.deadbeef.tmp"
    stale.write_text("partial", encoding="utf-8")
    os.utime(stale, (100, 100))
    unrelated = reports / "unrelated.tmp"
    unrelated.write_text("keep", encoding="utf-8")

    status = inspect_local_state(tmp_path, policy, now=1_000)
    assert status.stale_temporary_files == 1
    assert stale.exists()

    repaired = repair_local_state(tmp_path, policy, now=1_000)
    assert repaired.stale_temporary_files_removed == 1
    assert not stale.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_stale_trace_temp_matches_only_configured_generated_name(tmp_path: Path) -> None:
    policy = _policy(
        tmp_path,
        trace_store_path="state/generated/custom-trace.jsonl",
        stale_temp_age_seconds=60,
    )
    directory = tmp_path / "state" / "generated"
    directory.mkdir(parents=True)
    recognized = directory / (
        ".custom-trace.jsonl.repair-00000000000000000000000000000000.tmp"
    )
    unrelated = directory / (
        ".execution-traces.jsonl.repair-00000000000000000000000000000000.tmp"
    )
    recognized.write_bytes(b"partial")
    unrelated.write_bytes(b"keep")
    os.utime(recognized, (100, 100))
    os.utime(unrelated, (100, 100))

    result = repair_local_state(tmp_path, policy, now=1_000)
    assert result.stale_temporary_files_removed == 1
    assert not recognized.exists()
    assert unrelated.read_bytes() == b"keep"


def test_torn_trace_tail_recovery_preserves_prior_valid_records(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    path = tmp_path / policy.trace_store_path
    path.parent.mkdir(parents=True)
    valid = serialize_trace(_trace("preserved")).encode("utf-8") + b"\n"
    path.write_bytes(valid + b'{"trace_id":"incomplete"')

    status = inspect_local_state(tmp_path, policy)
    assert status.recoverable_torn_trace_tail
    assert status.corrupted_generated_files == 0

    result = repair_local_state(tmp_path, policy)
    assert result.torn_trace_tails_recovered == 1
    assert RECOVERED_TORN_TRACE_TAIL in result.error_codes
    assert path.read_bytes() == valid
    assert scan_trace_store(tmp_path, policy).traces[0].trace_id == "preserved"
    assert repair_local_state(tmp_path, policy).torn_trace_tails_recovered == 0


def test_valid_trace_without_final_newline_is_normalized(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    path = tmp_path / policy.trace_store_path
    path.parent.mkdir(parents=True)
    path.write_text(serialize_trace(_trace("valid-tail")), encoding="utf-8")

    result = repair_local_state(tmp_path, policy)
    assert result.torn_trace_tails_recovered == 1
    assert path.read_bytes().endswith(b"\n")
    assert scan_trace_store(tmp_path, policy).invalid_records == 0


def test_complete_trace_corruption_is_quarantined_and_valid_records_survive(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    path = tmp_path / policy.trace_store_path
    path.parent.mkdir(parents=True)
    valid = serialize_trace(_trace("survivor")).encode("utf-8") + b"\n"
    path.write_bytes(valid + b"{broken}\n")

    status = inspect_local_state(tmp_path, policy)
    assert status.corrupted_generated_files == 1
    assert not status.recoverable_torn_trace_tail

    result = repair_local_state(tmp_path, policy)
    assert result.corrupted_files_quarantined == 1
    assert CORRUPT_GENERATED_STATE in result.error_codes
    assert path.read_bytes() == valid
    quarantine = tmp_path / Path(policy.trace_store_path).parent / "quarantine"
    candidates = list(quarantine.glob("corrupt-*.jsonl"))
    assert len(candidates) == 1
    assert candidates[0].resolve().is_relative_to(tmp_path.resolve())
    assert repair_local_state(tmp_path, policy).corrupted_files_quarantined == 0
    assert len(list(quarantine.glob("corrupt-*.jsonl"))) == 1


def test_corrupt_report_is_quarantined_without_touching_unrelated_file(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    reports = tmp_path / policy.doctor_reports_dir
    reports.mkdir(parents=True)
    corrupt = reports / "doctor-20260714T000000000000Z.json"
    corrupt.write_text("{broken", encoding="utf-8")
    unrelated = reports / "notes.json"
    unrelated.write_text("TOP-SECRET-KEEP", encoding="utf-8")

    result = repair_local_state(tmp_path, policy)
    assert result.corrupted_files_quarantined == 1
    assert not corrupt.exists()
    assert unrelated.read_text(encoding="utf-8") == "TOP-SECRET-KEEP"


def test_oversized_trace_is_quarantined_without_reading_payload(tmp_path: Path) -> None:
    policy = _policy(tmp_path, max_trace_file_bytes=1024)
    path = tmp_path / policy.trace_store_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * 1025)

    assert inspect_local_state(tmp_path, policy).corrupted_generated_files == 1
    result = repair_local_state(tmp_path, policy)
    assert result.corrupted_files_quarantined == 1
    assert not path.exists()
    quarantine = tmp_path / Path(policy.trace_store_path).parent / "quarantine"
    assert len(list(quarantine.glob("corrupt-*.bin"))) == 1


def test_oversized_complete_line_is_quarantined(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    path = tmp_path / policy.trace_store_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * (MAX_TRACE_CHARS + 1) + b"\n")

    result = repair_local_state(tmp_path, policy)
    assert result.corrupted_files_quarantined == 1
    assert path.read_bytes() == b""


def test_quarantine_retention_is_bounded_and_preserves_unknown_files(tmp_path: Path) -> None:
    policy = _policy(tmp_path, retained_quarantine_files=2, max_state_scan_files=8)
    quarantine = tmp_path / Path(policy.trace_store_path).parent / "quarantine"
    quarantine.mkdir(parents=True)
    for index in range(4):
        path = quarantine / f"corrupt-trace-{index:016x}.jsonl"
        path.write_text("x", encoding="utf-8")
        os.utime(path, (100 + index, 100 + index))
    unknown = quarantine / "keep-me.txt"
    unknown.write_text("keep", encoding="utf-8")

    result = repair_local_state(tmp_path, policy, now=1_000)
    assert result.quarantine_files_removed == 2
    assert len(list(quarantine.glob("corrupt-*.jsonl"))) == 2
    assert unknown.read_text(encoding="utf-8") == "keep"


def test_directory_scan_cap_is_reported(tmp_path: Path) -> None:
    policy = _policy(
        tmp_path, max_state_scan_files=2, retained_quarantine_files=1
    )
    reports = tmp_path / policy.doctor_reports_dir
    reports.mkdir(parents=True)
    for index in range(5):
        (reports / f"doctor-20260714T00000000000{index}Z.json").write_text(
            "{}", encoding="utf-8"
        )

    status = inspect_local_state(tmp_path, policy)
    assert status.scan_limit_reached
    assert STATE_SCAN_LIMIT_REACHED in status.error_codes


def test_state_status_is_read_only_and_safe(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    status = inspect_local_state(tmp_path, policy)
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    assert before == after == []
    assert status.lock_available
    assert str(tmp_path) not in format_state_status(status)
    assert not hasattr(status, "__dict__")
    with pytest.raises(FrozenInstanceError):
        status.lock_available = False


@pytest.mark.parametrize(
    "command",
    (
        "/doctor state",
        "/doctor state repair ../outside",
        "/doctor state repair C:/outside",
        "/doctor state status .",
        "/DOCTOR STATE REPAIR",
        "/doctor  state  repair",
        "/doctor state repai",
    ),
)
def test_invalid_state_commands_never_mutate(tmp_path: Path, capsys, command: str) -> None:
    _write_policy(tmp_path)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    handle_doctor_command(tmp_path, command)

    assert capsys.readouterr().out.startswith("Unknown doctor command.\n")
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert before == after
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_exact_state_commands_have_deterministic_contract(tmp_path: Path, capsys) -> None:
    _write_policy(tmp_path)
    handle_doctor_command(tmp_path, "/doctor state status")
    status_output = capsys.readouterr().out
    assert status_output.startswith("Local state integrity\n")
    assert str(tmp_path) not in status_output

    handle_doctor_command(tmp_path, "/doctor state repair")
    repair_output = capsys.readouterr().out
    assert repair_output.startswith("Local state repair: complete\n")
    assert str(tmp_path) not in repair_output


def test_secret_sentinel_never_crosses_state_diagnostics_boundary(tmp_path: Path) -> None:
    secret = "TOP-SECRET-STATE-SENTINEL"
    policy = _policy(tmp_path)
    path = tmp_path / policy.trace_store_path
    path.parent.mkdir(parents=True)
    path.write_text(secret + "\n", encoding="utf-8")

    status = inspect_local_state(tmp_path, policy)
    rendered = repr(status) + repr(status.to_safe_dict()) + format_state_status(status)
    assert secret not in rendered
    assert str(tmp_path) not in rendered


def test_lock_failure_does_not_change_trace_public_result(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")

    def fail(self: GeneratedStateLock) -> GeneratedStateLock:
        raise StateLockError(STATE_LOCK_TIMEOUT)

    monkeypatch.setattr(GeneratedStateLock, "__enter__", fail)
    assert append_trace(tmp_path, _trace("safe-failure"), _policy(tmp_path)) is None
    assert not (tmp_path / "logs" / "diagnostics" / "execution-traces.jsonl").exists()


def test_v210_and_v211_trace_shape_remains_readable(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    path = tmp_path / policy.trace_store_path
    path.parent.mkdir(parents=True)
    old_record = _trace("legacy").to_safe_dict()
    path.write_text(json.dumps(old_record) + "\n", encoding="utf-8")

    scan = scan_trace_store(tmp_path, policy)
    assert [trace.trace_id for trace in scan.traces] == ["legacy"]
    assert scan.invalid_records == 0


def test_state_model_rejects_absolute_paths_and_unknown_codes() -> None:
    with pytest.raises(ValueError):
        StateIntegrityDiagnostics(
            True, 0, False, 0, 0, False, "C:/secret", "reports", "quarantine"
        )
    with pytest.raises(ValueError):
        StateIntegrityDiagnostics(
            True,
            0,
            False,
            0,
            0,
            False,
            "logs/traces.jsonl",
            "logs/reports",
            "logs/quarantine",
            ("TOP-SECRET-CODE",),
        )
