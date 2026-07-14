"""Bounded local-state coordination, inspection, and explicit recovery."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import threading
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO, Protocol

from core.execution_trace import MAX_TRACE_CHARS, ExecutionTrace, TraceError


MAX_LOCK_TIMEOUT_MS = 5_000
MAX_STALE_TEMP_AGE_SECONDS = 7 * 24 * 60 * 60
MAX_STATE_SCAN_FILES = 128
MAX_QUARANTINE_FILES = 20
MAX_RECOVERY_RECORDS = 1_000
MAX_QUARANTINE_NAME_CHARS = 180
MAX_STATE_RELATIVE_PATH_CHARS = 240

STATE_LOCK_UNAVAILABLE = "state_lock_unavailable"
STATE_LOCK_TIMEOUT = "state_lock_timeout"
STATE_LOCK_OPERATION_FAILED = "state_lock_operation_failed"
STALE_TEMPORARY_STATE = "stale_temporary_state"
RECOVERED_TORN_TRACE_TAIL = "recovered_torn_trace_tail"
CORRUPT_GENERATED_STATE = "corrupt_generated_state"
QUARANTINE_FAILED = "quarantine_failed"
STATE_REPAIR_FAILED = "state_repair_failed"
STATE_SCAN_LIMIT_REACHED = "state_scan_limit_reached"

STATE_ERROR_CODES = frozenset(
    {
        STATE_LOCK_UNAVAILABLE,
        STATE_LOCK_TIMEOUT,
        STATE_LOCK_OPERATION_FAILED,
        STALE_TEMPORARY_STATE,
        RECOVERED_TORN_TRACE_TAIL,
        CORRUPT_GENERATED_STATE,
        QUARANTINE_FAILED,
        STATE_REPAIR_FAILED,
        STATE_SCAN_LIMIT_REACHED,
    }
)

_LOCK_NAMES = {
    "trace": ".trace-state.lock",
    "reports": ".report-state.lock",
    "workflows": ".workflow-state.lock",
}
_THREAD_LOCKS = {
    "trace": threading.Lock(),
    "reports": threading.Lock(),
    "workflows": threading.Lock(),
}
_BLOCKED_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".cache",
        "cache",
        "node_modules",
    }
)
_REPORT_NAME = re.compile(r"^doctor-\d{8}T\d{12}Z\.json$")
_REPORT_TEMP_NAME = re.compile(
    r"^\.doctor-\d{8}T\d{12}Z\.json\.[A-Za-z0-9_-]{1,64}\.tmp$"
)
_QUARANTINE_TEMP_NAME = re.compile(r"^\.quarantine-[0-9a-f]{32}\.tmp$")
_QUARANTINE_NAME = re.compile(
    r"^corrupt-[A-Za-z0-9_.-]{1,120}-[0-9a-f]{16}\.(?:json|jsonl|bin)$"
)
_REPORT_FIELDS_V1 = frozenset(
    {
        "schema_version",
        "version",
        "created_at",
        "report_type",
        "status",
        "error_codes",
        "production_snapshot",
        "model_runtime",
        "documents",
        "memory",
        "terminal_policy",
        "execution_traces",
        "runtime_files",
    }
)
_REPORT_FIELDS_V2 = _REPORT_FIELDS_V1 | {"local_state"}
_REPORT_FIELDS_V2_WORKFLOWS = _REPORT_FIELDS_V2 | {"controlled_workflows"}


class StateIntegrityError(RuntimeError):
    """A safe local-state operation failure with a fixed public code."""

    def __init__(self, code: str) -> None:
        if code not in STATE_ERROR_CODES:
            raise ValueError("state integrity error code is not allowlisted")
        super().__init__(code)
        self.code = code


class StateLockError(StateIntegrityError):
    """A bounded lock acquisition, use, or release failure."""


class _LockBusy(Exception):
    pass


class _StateFileTooLarge(Exception):
    pass


class LockAdapter(Protocol):
    def acquire(self, stream: BinaryIO) -> None: ...

    def release(self, stream: BinaryIO) -> None: ...


class PosixLockAdapter:
    """Non-blocking POSIX advisory file-lock adapter."""

    def acquire(self, stream: BinaryIO) -> None:
        import fcntl

        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise _LockBusy from exc

    def release(self, stream: BinaryIO) -> None:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class WindowsLockAdapter:
    """Non-blocking Windows byte-range file-lock adapter."""

    def acquire(self, stream: BinaryIO) -> None:
        import msvcrt

        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(
                exc, "winerror", None
            ) in {32, 33, 36}:
                raise _LockBusy from exc
            raise

    def release(self, stream: BinaryIO) -> None:
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def platform_lock_adapter() -> LockAdapter:
    return WindowsLockAdapter() if os.name == "nt" else PosixLockAdapter()


def _open_lock_stream(path: Path, *, create: bool) -> BinaryIO:
    if path.is_symlink():
        raise StateLockError(STATE_LOCK_UNAVAILABLE)
    flags = os.O_RDWR | (os.O_CREAT if create else 0)
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        stream = os.fdopen(descriptor, "r+b")
        descriptor = None
        return stream
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validated_directory(project_root: Path, directory: Path) -> tuple[Path, Path]:
    if not isinstance(project_root, Path) or not isinstance(directory, Path):
        raise StateLockError(STATE_LOCK_UNAVAILABLE)
    root = project_root.resolve()
    target = directory.resolve(strict=False)
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise StateLockError(STATE_LOCK_UNAVAILABLE) from exc
    if not relative.parts or any(part.lower() in _BLOCKED_PARTS for part in relative.parts):
        raise StateLockError(STATE_LOCK_UNAVAILABLE)
    return root, target


class GeneratedStateLock:
    """Fixed-name lock confined to a validated generated-state directory."""

    __slots__ = (
        "_adapter",
        "_directory",
        "_file_locked",
        "_scope",
        "_stream",
        "_thread_locked",
        "_timeout_seconds",
        "_root",
    )

    def __init__(
        self,
        project_root: Path,
        directory: Path,
        scope: str,
        timeout_ms: int,
        *,
        adapter: LockAdapter | None = None,
    ) -> None:
        if scope not in _LOCK_NAMES:
            raise StateLockError(STATE_LOCK_UNAVAILABLE)
        if type(timeout_ms) is not int or not 0 <= timeout_ms <= MAX_LOCK_TIMEOUT_MS:
            raise StateLockError(STATE_LOCK_UNAVAILABLE)
        self._root, self._directory = _validated_directory(project_root, directory)
        self._scope = scope
        self._timeout_seconds = timeout_ms / 1000
        self._adapter = adapter if adapter is not None else platform_lock_adapter()
        self._stream: BinaryIO | None = None
        self._thread_locked = False
        self._file_locked = False

    @property
    def lock_path(self) -> Path:
        return self._directory / _LOCK_NAMES[self._scope]

    def acquire(self) -> "GeneratedStateLock":
        deadline = time.monotonic() + self._timeout_seconds
        if not _THREAD_LOCKS[self._scope].acquire(timeout=self._timeout_seconds):
            raise StateLockError(STATE_LOCK_TIMEOUT)
        self._thread_locked = True
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            _validated_directory(self._root, self._directory)
            stream = _open_lock_stream(self.lock_path, create=True)
            self._stream = stream
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
                os.fsync(stream.fileno())
            while True:
                try:
                    self._adapter.acquire(stream)
                    self._file_locked = True
                    return self
                except _LockBusy:
                    if time.monotonic() >= deadline:
                        raise StateLockError(STATE_LOCK_TIMEOUT)
                    time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
        except StateLockError:
            self._cleanup_after_failed_acquire()
            raise
        except OSError as exc:
            self._cleanup_after_failed_acquire()
            raise StateLockError(STATE_LOCK_OPERATION_FAILED) from exc
        except Exception as exc:
            self._cleanup_after_failed_acquire()
            raise StateLockError(STATE_LOCK_OPERATION_FAILED) from exc

    def _cleanup_after_failed_acquire(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
            self._stream = None
        if self._thread_locked:
            _THREAD_LOCKS[self._scope].release()
            self._thread_locked = False

    def release(self) -> None:
        failed = False
        stream = self._stream
        try:
            if self._file_locked and stream is not None:
                self._adapter.release(stream)
        except Exception:
            failed = True
        finally:
            self._file_locked = False
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    failed = True
                self._stream = None
            if self._thread_locked:
                _THREAD_LOCKS[self._scope].release()
                self._thread_locked = False
        if failed:
            raise StateLockError(STATE_LOCK_OPERATION_FAILED)

    def __enter__(self) -> "GeneratedStateLock":
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        try:
            self.release()
        except StateLockError:
            if exc is None:
                raise
        return False


def probe_generated_state_lock(
    project_root: Path,
    directory: Path,
    scope: str,
    *,
    adapter: LockAdapter | None = None,
) -> tuple[bool, str]:
    """Probe an existing lock without creating directories or lock files."""

    try:
        _, target = _validated_directory(project_root, directory)
        if scope not in _LOCK_NAMES:
            return False, STATE_LOCK_UNAVAILABLE
        lock_path = target / _LOCK_NAMES[scope]
        if not target.exists() or not lock_path.exists():
            return True, ""
        stream = _open_lock_stream(lock_path, create=False)
        active_adapter = adapter if adapter is not None else platform_lock_adapter()
        try:
            active_adapter.acquire(stream)
        except _LockBusy:
            return False, STATE_LOCK_TIMEOUT
        try:
            active_adapter.release(stream)
        finally:
            stream.close()
        return True, ""
    except StateLockError as exc:
        return False, exc.code
    except OSError:
        return False, STATE_LOCK_OPERATION_FAILED
    except Exception:
        return False, STATE_LOCK_OPERATION_FAILED


@dataclass(frozen=True, slots=True)
class StateIntegrityDiagnostics:
    lock_available: bool
    stale_temporary_files: int
    recoverable_torn_trace_tail: bool
    corrupted_generated_files: int
    quarantined_files: int
    scan_limit_reached: bool
    trace_store_path: str
    reports_path: str
    quarantine_path: str
    error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        flags = (
            self.lock_available,
            self.recoverable_torn_trace_tail,
            self.scan_limit_reached,
        )
        if any(type(flag) is not bool for flag in flags):
            raise ValueError("state integrity flags must be booleans")
        for count in (
            self.stale_temporary_files,
            self.corrupted_generated_files,
            self.quarantined_files,
        ):
            if type(count) is not int or not 0 <= count <= MAX_STATE_SCAN_FILES:
                raise ValueError("state integrity count is outside the hard limit")
        for relative in (self.trace_store_path, self.reports_path, self.quarantine_path):
            candidate = Path(relative)
            if (
                len(relative) > MAX_STATE_RELATIVE_PATH_CHARS
                or PureWindowsPath(relative).is_absolute()
                or PureWindowsPath(relative).drive
                or PurePosixPath(relative).is_absolute()
                or ".." in candidate.parts
            ):
                raise ValueError("state integrity paths must be relative")
        if any(code not in STATE_ERROR_CODES for code in self.error_codes):
            raise ValueError("state integrity code is not allowlisted")
        object.__setattr__(self, "error_codes", tuple(dict.fromkeys(self.error_codes)))

    @property
    def status(self) -> str:
        return "healthy" if not self.error_codes else "degraded"

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "lock_available": self.lock_available,
            "stale_temporary_files": self.stale_temporary_files,
            "recoverable_torn_trace_tail": self.recoverable_torn_trace_tail,
            "corrupted_generated_files": self.corrupted_generated_files,
            "quarantined_files": self.quarantined_files,
            "scan_limit_reached": self.scan_limit_reached,
            "trace_store_path": Path(self.trace_store_path).as_posix(),
            "reports_path": Path(self.reports_path).as_posix(),
            "quarantine_path": Path(self.quarantine_path).as_posix(),
            "error_codes": list(self.error_codes),
        }


@dataclass(frozen=True, slots=True)
class StateRepairResult:
    stale_temporary_files_removed: int
    torn_trace_tails_recovered: int
    corrupted_files_quarantined: int
    quarantine_files_removed: int
    error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for count in (
            self.stale_temporary_files_removed,
            self.torn_trace_tails_recovered,
            self.corrupted_files_quarantined,
            self.quarantine_files_removed,
        ):
            if type(count) is not int or not 0 <= count <= MAX_STATE_SCAN_FILES:
                raise ValueError("state repair count is outside the hard limit")
        if any(code not in STATE_ERROR_CODES for code in self.error_codes):
            raise ValueError("state repair code is not allowlisted")
        object.__setattr__(self, "error_codes", tuple(dict.fromkeys(self.error_codes)))

    @property
    def succeeded(self) -> bool:
        return not any(
            code
            in {
                STATE_LOCK_UNAVAILABLE,
                STATE_LOCK_TIMEOUT,
                STATE_LOCK_OPERATION_FAILED,
                QUARANTINE_FAILED,
                STATE_REPAIR_FAILED,
            }
            for code in self.error_codes
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "succeeded": self.succeeded,
            "stale_temporary_files_removed": self.stale_temporary_files_removed,
            "torn_trace_tails_recovered": self.torn_trace_tails_recovered,
            "corrupted_files_quarantined": self.corrupted_files_quarantined,
            "quarantine_files_removed": self.quarantine_files_removed,
            "error_codes": list(self.error_codes),
        }


@dataclass(frozen=True, slots=True)
class _TraceAnalysis:
    path: Path
    original: bytes
    repaired: bytes
    torn_tail: bool
    corrupt: bool
    limit_reached: bool
    oversized: bool


def _trace_paths(root: Path, policy: Any) -> tuple[Path, ...]:
    active = root / policy.trace_store_path
    paths = [active]
    paths.extend(
        active.with_name(f"{active.name}.{index}")
        for index in range(1, policy.retained_trace_backups + 1)
    )
    return tuple(paths[: policy.max_trace_scan_files])


def _trace_repair_temp_pattern(policy: Any) -> re.Pattern[str]:
    active_name = re.escape(Path(policy.trace_store_path).name)
    if policy.retained_trace_backups:
        backup_indexes = "|".join(
            str(index) for index in range(1, policy.retained_trace_backups + 1)
        )
        generated_name = rf"{active_name}(?:\.(?:{backup_indexes}))?"
    else:
        generated_name = active_name
    return re.compile(rf"^\.{generated_name}\.repair-[0-9a-f]{{32}}\.tmp$")


def _analyze_trace(path: Path, maximum_bytes: int) -> _TraceAnalysis | None:
    try:
        if path.is_symlink():
            return _TraceAnalysis(path, b"", b"", False, True, True, False)
        if not path.is_file():
            return None
        original = _read_bounded_file(path, maximum_bytes)
    except _StateFileTooLarge:
        return _TraceAnalysis(path, b"", b"", False, True, False, True)
    except OSError:
        return _TraceAnalysis(path, b"", b"", False, True, False, False)
    lines = original.splitlines(keepends=True)
    if len(lines) > MAX_RECOVERY_RECORDS:
        return _TraceAnalysis(path, original, original, False, False, True, False)
    repaired: list[bytes] = []
    corrupt = False
    torn = bool(lines and not lines[-1].endswith(b"\n"))
    for index, raw in enumerate(lines):
        final_torn = torn and index == len(lines) - 1
        payload = raw.rstrip(b"\r\n")
        if not payload.strip():
            continue
        if len(payload) > MAX_TRACE_CHARS:
            if not final_torn:
                corrupt = True
            continue
        try:
            value = json.loads(payload.decode("utf-8"))
            ExecutionTrace.from_safe_dict(value)
        except (UnicodeError, json.JSONDecodeError, TraceError, TypeError, ValueError):
            if not final_torn:
                corrupt = True
            continue
        repaired.append(payload + b"\n")
    return _TraceAnalysis(
        path, original, b"".join(repaired), torn, corrupt, False, False
    )


def _read_bounded_file(path: Path, maximum_bytes: int) -> bytes:
    if path.is_symlink():
        raise OSError
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        stream = os.fdopen(descriptor, "rb")
        descriptor = None
        with stream:
            content = stream.read(maximum_bytes + 1)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(content) > maximum_bytes:
        raise _StateFileTooLarge
    return content


def _valid_report_content(content: bytes) -> bool:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        return False
    expected = (
        {_REPORT_FIELDS_V1}
        if value["schema_version"] == 1
        else {_REPORT_FIELDS_V2, _REPORT_FIELDS_V2_WORKFLOWS}
    )
    return (
        value["schema_version"] in {1, 2}
        and set(value) in expected
        and value.get("report_type") == "runtime_diagnostics"
        and isinstance(value.get("version"), str)
        and isinstance(value.get("created_at"), str)
        and isinstance(value.get("status"), str)
        and isinstance(value.get("error_codes"), list)
    )


def _bounded_named_files(directory: Path, pattern: re.Pattern[str], limit: int) -> tuple[list[Path], bool]:
    values: list[Path] = []
    if not directory.is_dir():
        return values, False
    try:
        with os.scandir(directory) as entries:
            scanned = 0
            for entry in entries:
                if scanned >= limit:
                    return values, True
                scanned += 1
                if entry.is_file(follow_symlinks=False) and pattern.fullmatch(entry.name):
                    values.append(Path(entry.path))
    except OSError:
        return values, True
    return values, False


def _is_stale(path: Path, age_seconds: int, now: float) -> bool:
    try:
        return now - path.stat().st_mtime >= age_seconds
    except OSError:
        return False


def _quarantine_relative(policy: Any) -> Path:
    return Path(policy.trace_store_path).parent / "quarantine"


def inspect_local_state(
    project_root: Path,
    policy: Any,
    *,
    now: float | None = None,
) -> StateIntegrityDiagnostics:
    """Inspect only recognized generated state without mutating the filesystem."""

    root = project_root.resolve()
    trace_path = root / policy.trace_store_path
    trace_directory = trace_path.parent
    reports_directory = root / policy.doctor_reports_dir
    quarantine_relative = _quarantine_relative(policy)
    quarantine_directory = root / quarantine_relative
    errors: list[str] = []
    timestamp = time.time() if now is None else now

    try:
        for directory in (trace_directory, reports_directory, quarantine_directory):
            _validated_directory(root, directory)
    except StateLockError:
        return StateIntegrityDiagnostics(
            lock_available=False,
            stale_temporary_files=0,
            recoverable_torn_trace_tail=False,
            corrupted_generated_files=0,
            quarantined_files=0,
            scan_limit_reached=False,
            trace_store_path=Path(policy.trace_store_path).as_posix(),
            reports_path=Path(policy.doctor_reports_dir).as_posix(),
            quarantine_path=quarantine_relative.as_posix(),
            error_codes=(STATE_LOCK_UNAVAILABLE,),
        )

    trace_lock, trace_code = probe_generated_state_lock(root, trace_directory, "trace")
    report_lock, report_code = probe_generated_state_lock(root, reports_directory, "reports")
    lock_available = trace_lock and report_lock
    for code in (trace_code, report_code):
        if code and code not in errors:
            errors.append(code)

    stale = 0
    scan_limit = False
    for directory, pattern in (
        (reports_directory, _REPORT_TEMP_NAME),
        (trace_directory, _trace_repair_temp_pattern(policy)),
        (quarantine_directory, _QUARANTINE_TEMP_NAME),
    ):
        files, limited = _bounded_named_files(directory, pattern, policy.max_state_scan_files)
        scan_limit = scan_limit or limited
        stale += sum(_is_stale(path, policy.stale_temp_age_seconds, timestamp) for path in files)
        stale = min(stale, policy.max_state_scan_files)

    torn = False
    corrupt = 0
    for path in _trace_paths(root, policy):
        analysis = _analyze_trace(path, policy.max_trace_file_bytes)
        if analysis is None:
            continue
        torn = torn or analysis.torn_tail
        corrupt += int(analysis.corrupt)
        scan_limit = scan_limit or analysis.limit_reached

    reports, reports_limited = _bounded_named_files(
        reports_directory, _REPORT_NAME, policy.max_state_scan_files
    )
    scan_limit = scan_limit or reports_limited
    for path in reports:
        try:
            content = _read_bounded_file(path, policy.max_doctor_report_bytes)
            if not _valid_report_content(content):
                raise ValueError
        except (OSError, _StateFileTooLarge, ValueError):
            corrupt += 1
            if corrupt >= policy.max_state_scan_files:
                scan_limit = True
                corrupt = policy.max_state_scan_files
                break

    quarantined, quarantine_limited = _bounded_named_files(
        quarantine_directory, _QUARANTINE_NAME, policy.max_state_scan_files
    )
    scan_limit = scan_limit or quarantine_limited
    if stale:
        errors.append(STALE_TEMPORARY_STATE)
    if corrupt:
        errors.append(CORRUPT_GENERATED_STATE)
    if scan_limit:
        errors.append(STATE_SCAN_LIMIT_REACHED)
    return StateIntegrityDiagnostics(
        lock_available=lock_available,
        stale_temporary_files=stale,
        recoverable_torn_trace_tail=torn,
        corrupted_generated_files=min(corrupt, policy.max_state_scan_files),
        quarantined_files=min(len(quarantined), policy.max_state_scan_files),
        scan_limit_reached=scan_limit,
        trace_store_path=Path(policy.trace_store_path).as_posix(),
        reports_path=Path(policy.doctor_reports_dir).as_posix(),
        quarantine_path=quarantine_relative.as_posix(),
        error_codes=tuple(errors),
    )


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.repair-{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _quarantine_copy(source: Path, content: bytes, directory: Path) -> bool:
    digest = hashlib.sha256(content).hexdigest()[:16]
    safe_source = re.sub(r"[^A-Za-z0-9_.-]", "-", source.name)[:120]
    suffix = "jsonl" if ".jsonl" in source.name else "json" if source.suffix == ".json" else "bin"
    name = f"corrupt-{safe_source}-{digest}.{suffix}"
    if len(name) > MAX_QUARANTINE_NAME_CHARS or not _QUARANTINE_NAME.fullmatch(name):
        return False
    target = directory / name
    temporary = directory / f".quarantine-{uuid.uuid4().hex}.tmp"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_symlink() or not target.is_file():
                return False
            try:
                existing = _read_bounded_file(target, len(content))
            except (OSError, _StateFileTooLarge):
                return False
            return hashlib.sha256(existing).digest() == hashlib.sha256(content).digest()
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        return True
    except OSError:
        return False
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _quarantine_oversized(source: Path, directory: Path) -> bool:
    """Atomically confine an oversized generated file without reading its payload."""

    safe_source = re.sub(r"[^A-Za-z0-9_.-]", "-", source.name)[:120]
    name = f"corrupt-{safe_source}-{uuid.uuid4().hex[:16]}.bin"
    if len(name) > MAX_QUARANTINE_NAME_CHARS or not _QUARANTINE_NAME.fullmatch(name):
        return False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        os.replace(source, directory / name)
        return True
    except OSError:
        return False


def _remove_stale_temps(
    directory: Path,
    pattern: re.Pattern[str],
    policy: Any,
    now: float,
) -> tuple[int, bool, bool]:
    removed = 0
    files, limited = _bounded_named_files(directory, pattern, policy.max_state_scan_files)
    for path in files:
        if not _is_stale(path, policy.stale_temp_age_seconds, now):
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            return removed, limited, True
    return removed, limited, False


def _retain_quarantine(
    directory: Path, keep: int, scan_limit: int
) -> tuple[int, bool, bool]:
    files, limited = _bounded_named_files(directory, _QUARANTINE_NAME, scan_limit)
    try:
        ordered = sorted(files, key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)
    except OSError:
        return 0, limited, True
    removed = 0
    for path in ordered[keep:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            return removed, limited, True
    return removed, limited, False


def repair_local_state(
    project_root: Path,
    policy: Any,
    *,
    now: float | None = None,
) -> StateRepairResult:
    """Explicitly repair only recognized generated state under bounded locks."""

    root = project_root.resolve()
    trace_path = root / policy.trace_store_path
    trace_directory = trace_path.parent
    reports_directory = root / policy.doctor_reports_dir
    quarantine_directory = root / _quarantine_relative(policy)
    stale_removed = torn_recovered = corrupt_quarantined = quarantine_removed = 0
    errors: list[str] = []
    timestamp = time.time() if now is None else now

    try:
        for directory in (trace_directory, reports_directory, quarantine_directory):
            _validated_directory(root, directory)
    except StateLockError as exc:
        return StateRepairResult(0, 0, 0, 0, (exc.code,))

    existing_scopes = []
    if trace_directory.exists():
        existing_scopes.append((trace_directory, "trace"))
    if reports_directory.exists():
        existing_scopes.append((reports_directory, "reports"))
    try:
        with ExitStack() as stack:
            for directory, scope in existing_scopes:
                stack.enter_context(
                    GeneratedStateLock(root, directory, scope, policy.lock_timeout_ms)
                )

            for path in _trace_paths(root, policy):
                analysis = _analyze_trace(path, policy.max_trace_file_bytes)
                if analysis is None:
                    continue
                if analysis.limit_reached:
                    errors.append(STATE_SCAN_LIMIT_REACHED)
                    continue
                if analysis.corrupt:
                    content = analysis.original
                    if not content:
                        if analysis.oversized:
                            if not _quarantine_oversized(path, quarantine_directory):
                                errors.extend((QUARANTINE_FAILED, STATE_REPAIR_FAILED))
                                continue
                            corrupt_quarantined += 1
                            continue
                        errors.extend((QUARANTINE_FAILED, STATE_REPAIR_FAILED))
                        continue
                    if not _quarantine_copy(path, content, quarantine_directory):
                        errors.extend((QUARANTINE_FAILED, STATE_REPAIR_FAILED))
                        continue
                    try:
                        _atomic_write(path, analysis.repaired)
                    except OSError:
                        errors.append(STATE_REPAIR_FAILED)
                        continue
                    corrupt_quarantined += 1
                elif analysis.torn_tail:
                    try:
                        _atomic_write(path, analysis.repaired)
                    except OSError:
                        errors.append(STATE_REPAIR_FAILED)
                        continue
                    torn_recovered += 1

            reports, limited = _bounded_named_files(
                reports_directory, _REPORT_NAME, policy.max_state_scan_files
            )
            if limited:
                errors.append(STATE_SCAN_LIMIT_REACHED)
            for path in reports:
                try:
                    content = _read_bounded_file(
                        path, policy.max_doctor_report_bytes
                    )
                    if not _valid_report_content(content):
                        raise ValueError
                    continue
                except _StateFileTooLarge:
                    if not _quarantine_oversized(path, quarantine_directory):
                        errors.extend((QUARANTINE_FAILED, STATE_REPAIR_FAILED))
                        continue
                    corrupt_quarantined += 1
                    continue
                except (OSError, ValueError):
                    try:
                        content = _read_bounded_file(
                            path, policy.max_doctor_report_bytes
                        )
                    except (OSError, _StateFileTooLarge):
                        errors.append(STATE_REPAIR_FAILED)
                        continue
                if not _quarantine_copy(path, content, quarantine_directory):
                    errors.extend((QUARANTINE_FAILED, STATE_REPAIR_FAILED))
                    continue
                try:
                    path.unlink()
                except OSError:
                    errors.append(STATE_REPAIR_FAILED)
                    continue
                corrupt_quarantined += 1

            for directory, pattern in (
                (reports_directory, _REPORT_TEMP_NAME),
                (trace_directory, _trace_repair_temp_pattern(policy)),
                (quarantine_directory, _QUARANTINE_TEMP_NAME),
            ):
                removed, limited, failed = _remove_stale_temps(
                    directory, pattern, policy, timestamp
                )
                stale_removed += removed
                if limited:
                    errors.append(STATE_SCAN_LIMIT_REACHED)
                if failed:
                    errors.append(STATE_REPAIR_FAILED)

            quarantine_removed, limited, failed = _retain_quarantine(
                quarantine_directory,
                policy.retained_quarantine_files,
                policy.max_state_scan_files,
            )
            if limited:
                errors.append(STATE_SCAN_LIMIT_REACHED)
            if failed:
                errors.extend((QUARANTINE_FAILED, STATE_REPAIR_FAILED))
    except StateLockError as exc:
        errors.append(exc.code)
    except Exception:
        errors.append(STATE_REPAIR_FAILED)

    if torn_recovered:
        errors.append(RECOVERED_TORN_TRACE_TAIL)
    if corrupt_quarantined:
        errors.append(CORRUPT_GENERATED_STATE)
    return StateRepairResult(
        stale_temporary_files_removed=min(stale_removed, MAX_STATE_SCAN_FILES),
        torn_trace_tails_recovered=min(torn_recovered, MAX_STATE_SCAN_FILES),
        corrupted_files_quarantined=min(corrupt_quarantined, MAX_STATE_SCAN_FILES),
        quarantine_files_removed=min(quarantine_removed, MAX_STATE_SCAN_FILES),
        error_codes=tuple(dict.fromkeys(errors)),
    )


def format_state_status(status: StateIntegrityDiagnostics) -> str:
    if not isinstance(status, StateIntegrityDiagnostics):
        raise TypeError("status must be StateIntegrityDiagnostics")
    codes = ", ".join(status.error_codes) or "none"
    return "\n".join(
        (
            "Local state integrity",
            f"Lock available: {'yes' if status.lock_available else 'no'}",
            f"Stale temporary files: {status.stale_temporary_files}",
            f"Recoverable torn trace tail: {'yes' if status.recoverable_torn_trace_tail else 'no'}",
            f"Corrupted generated files: {status.corrupted_generated_files}",
            f"Quarantined files: {status.quarantined_files}",
            f"Status codes: {codes}",
        )
    )


def format_state_repair(result: StateRepairResult) -> str:
    if not isinstance(result, StateRepairResult):
        raise TypeError("result must be StateRepairResult")
    codes = ", ".join(result.error_codes) or "none"
    return "\n".join(
        (
            f"Local state repair: {'complete' if result.succeeded else 'failed'}",
            f"Stale temporary files removed: {result.stale_temporary_files_removed}",
            f"Torn trace tails recovered: {result.torn_trace_tails_recovered}",
            f"Corrupted files quarantined: {result.corrupted_files_quarantined}",
            f"Quarantine files removed: {result.quarantine_files_removed}",
            f"Status codes: {codes}",
        )
    )


__all__ = [
    "CORRUPT_GENERATED_STATE",
    "GeneratedStateLock",
    "LockAdapter",
    "MAX_LOCK_TIMEOUT_MS",
    "MAX_QUARANTINE_FILES",
    "MAX_STALE_TEMP_AGE_SECONDS",
    "MAX_STATE_SCAN_FILES",
    "PosixLockAdapter",
    "QUARANTINE_FAILED",
    "RECOVERED_TORN_TRACE_TAIL",
    "STALE_TEMPORARY_STATE",
    "STATE_ERROR_CODES",
    "STATE_LOCK_OPERATION_FAILED",
    "STATE_LOCK_TIMEOUT",
    "STATE_LOCK_UNAVAILABLE",
    "STATE_REPAIR_FAILED",
    "STATE_SCAN_LIMIT_REACHED",
    "StateIntegrityDiagnostics",
    "StateIntegrityError",
    "StateLockError",
    "StateRepairResult",
    "WindowsLockAdapter",
    "format_state_repair",
    "format_state_status",
    "inspect_local_state",
    "platform_lock_adapter",
    "probe_generated_state_lock",
    "repair_local_state",
]
