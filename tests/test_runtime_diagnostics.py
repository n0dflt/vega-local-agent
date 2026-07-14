from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.execution_trace import ExecutionTrace, TraceStatus, append_trace
from core.runtime_diagnostics import (
    MAX_DOCTOR_REPORT_BYTES,
    DiagnosticsError,
    DiagnosticsExportError,
    DiagnosticsPolicy,
    DiagnosticsPolicyError,
    DiagnosticsSerializationError,
    RuntimeDiagnosticsReport,
    build_runtime_diagnostics,
    export_diagnostics_report,
    get_trace_store_status,
    load_diagnostics_policy,
    serialize_diagnostics_report,
)


ROOT = Path(__file__).resolve().parents[1]


def _policy_value(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "trace_store_path": "logs/diagnostics/execution-traces.jsonl",
        "max_trace_file_bytes": 5 * 1024 * 1024,
        "retained_trace_backups": 3,
        "max_trace_scan_files": 4,
        "max_trace_records": 256,
        "doctor_reports_dir": "logs/diagnostics/reports",
        "max_doctor_report_bytes": 512 * 1024,
        "retained_doctor_reports": 3,
    }
    value.update(overrides)
    return value


def _write_policy(root: Path, **overrides: object) -> DiagnosticsPolicy:
    path = root / "config" / "diagnostics_policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_policy_value(**overrides), ensure_ascii=False),
        encoding="utf-8",
    )
    return load_diagnostics_policy(root)


def _model_status() -> dict[str, object]:
    return {
        "selection_mode": "auto",
        "current_profile": "code",
        "current_model": "qwen2.5-coder:14b",
        "ollama_available": True,
        "model_installed": True,
        "fallback_status": "not_used",
    }


def _report(root: Path, policy: DiagnosticsPolicy) -> RuntimeDiagnosticsReport:
    return build_runtime_diagnostics(
        root,
        policy=policy,
        created_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        model_status=_model_status(),
    )


def test_repository_diagnostics_policy_loads() -> None:
    policy = load_diagnostics_policy(ROOT)

    assert policy.schema_version == 1
    assert policy.retained_trace_backups == 3
    assert policy.max_trace_file_bytes == 5 * 1024 * 1024
    assert policy.trace_store_path == "logs/diagnostics/execution-traces.jsonl"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", 2),
        ("trace_store_path", "../secret.jsonl"),
        ("trace_store_path", "C:/secret.jsonl"),
        ("trace_store_path", ".git/trace.jsonl"),
        ("max_trace_file_bytes", 0),
        ("max_trace_file_bytes", 5 * 1024 * 1024 + 1),
        ("retained_trace_backups", -1),
        ("retained_trace_backups", 6),
        ("max_trace_records", True),
        ("retained_doctor_reports", 21),
    ),
)
def test_policy_rejects_unsafe_values(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    path = tmp_path / "config" / "diagnostics_policy.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_policy_value(**{field: value})), encoding="utf-8")

    with pytest.raises(DiagnosticsPolicyError):
        load_diagnostics_policy(tmp_path)


def test_policy_rejects_missing_unknown_and_duplicate_fields(tmp_path: Path) -> None:
    path = tmp_path / "config" / "diagnostics_policy.json"
    path.parent.mkdir(parents=True)
    value = _policy_value()
    value.pop("max_trace_records")
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(DiagnosticsPolicyError):
        load_diagnostics_policy(tmp_path)

    value = _policy_value(unknown=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(DiagnosticsPolicyError):
        load_diagnostics_policy(tmp_path)

    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(DiagnosticsPolicyError, match="duplicate"):
        load_diagnostics_policy(tmp_path)


def test_missing_and_malformed_policy_fail_safely(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticsPolicyError, match="missing"):
        load_diagnostics_policy(tmp_path)

    path = tmp_path / "config" / "diagnostics_policy.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(DiagnosticsPolicyError, match="could not be loaded"):
        load_diagnostics_policy(tmp_path)


def test_policy_rejects_symlink_escape_when_supported(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    path = tmp_path / "config" / "diagnostics_policy.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(_policy_value(doctor_reports_dir="linked/reports")),
        encoding="utf-8",
    )
    with pytest.raises(DiagnosticsPolicyError, match="escapes"):
        load_diagnostics_policy(tmp_path)


def test_report_is_immutable_allowlisted_and_deterministic(tmp_path: Path) -> None:
    policy = _write_policy(tmp_path)
    report = _report(tmp_path, policy)

    with pytest.raises(FrozenInstanceError):
        report.status = "healthy"
    value = report.to_safe_dict()
    assert set(value) == {
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
    first = serialize_diagnostics_report(report)
    second = serialize_diagnostics_report(report)
    assert first == second
    assert json.loads(first)["created_at"] == "2026-07-14T00:00:00.000000Z"


def test_report_rejects_invalid_status_and_size(tmp_path: Path) -> None:
    policy = _write_policy(tmp_path)
    report = _report(tmp_path, policy)

    with pytest.raises(DiagnosticsError, match="allowlisted"):
        replace(report, status="TOP-SECRET-DIAGNOSTICS")
    with pytest.raises(DiagnosticsSerializationError, match="too_large"):
        serialize_diagnostics_report(report, max_bytes=10)
    with pytest.raises(ValueError):
        serialize_diagnostics_report(report, max_bytes=MAX_DOCTOR_REPORT_BYTES + 1)


def test_report_and_serialization_exclude_secret_sentinels(tmp_path: Path) -> None:
    policy = _write_policy(tmp_path)
    report = _report(tmp_path, policy)
    rendered = repr(report) + repr(report.to_safe_dict()) + serialize_diagnostics_report(report)
    sentinels = (
        "TOP-SECRET-DIAGNOSTICS",
        "SYSTEM-PROMPT-SECRET",
        "CONFIRMATION-TOKEN-SECRET",
        "EVIDENCE-CONTENT-SECRET",
        r"C:\Users\Secret\private.txt",
        "https://example.com/path?token=SECRET",
    )
    assert all(sentinel not in rendered for sentinel in sentinels)
    assert str(tmp_path) not in serialize_diagnostics_report(report)


def test_trace_status_and_aggregate_are_bounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    policy = _write_policy(tmp_path, max_trace_records=2)
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    append_trace(tmp_path, ExecutionTrace("one", "contextual", status=TraceStatus.COMPLETED), policy)
    append_trace(tmp_path, ExecutionTrace("two", "contextual", status=TraceStatus.BLOCKED), policy)
    append_trace(tmp_path, ExecutionTrace("three", "other", status=TraceStatus.FAILED), policy)
    path = tmp_path / policy.trace_store_path
    with path.open("a", encoding="utf-8") as stream:
        stream.write("{corrupt\n")

    status = get_trace_store_status(tmp_path, policy)

    assert status.enabled
    assert status.valid_records == 2
    assert status.aggregate.scanned_records == 2
    assert status.aggregate.failed == 1
    assert status.aggregate.blocked == 1
    assert status.corrupt_records_detected
    assert "trace_scan_limit_reached" in status.error_codes


def test_export_is_explicit_atomic_relative_utf8_and_retained(tmp_path: Path) -> None:
    policy = _write_policy(tmp_path, retained_doctor_reports=2)
    report = _report(tmp_path, policy)
    reports = tmp_path / policy.doctor_reports_dir
    reports.mkdir(parents=True)
    unknown = reports / "keep-me.txt"
    unknown.write_text("TOP-SECRET-DIAGNOSTICS", encoding="utf-8")
    for stamp in ("20260101T000000000001Z", "20260101T000000000002Z"):
        (reports / f"doctor-{stamp}.json").write_text("{}", encoding="utf-8")

    result = export_diagnostics_report(tmp_path, policy=policy, report=report)

    assert not Path(result.relative_path).is_absolute()
    exported = tmp_path / result.relative_path
    assert exported.is_file()
    assert json.loads(exported.read_text(encoding="utf-8"))["report_type"] == "runtime_diagnostics"
    assert len(list(reports.glob("doctor-*.json"))) == 2
    assert unknown.read_text(encoding="utf-8") == "TOP-SECRET-DIAGNOSTICS"
    assert not list(reports.glob("*.tmp"))


def test_export_size_failure_leaves_no_partial_file(tmp_path: Path) -> None:
    policy = _write_policy(tmp_path, max_doctor_report_bytes=100)
    report = _report(tmp_path, policy)

    with pytest.raises(DiagnosticsExportError, match="too_large"):
        export_diagnostics_report(tmp_path, policy=policy, report=report)

    reports = tmp_path / policy.doctor_reports_dir
    assert not reports.exists()

