from __future__ import annotations

import json
from pathlib import Path

from core.agent_runtime import handle_doctor_command


def _policy(root: Path) -> None:
    path = root / "config" / "diagnostics_policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "trace_store_path": "logs/diagnostics/execution-traces.jsonl",
                "max_trace_file_bytes": 5242880,
                "retained_trace_backups": 3,
                "max_trace_scan_files": 4,
                "max_trace_records": 256,
                "doctor_reports_dir": "logs/diagnostics/reports",
                "max_doctor_report_bytes": 524288,
                "retained_doctor_reports": 3,
                "lock_timeout_ms": 500,
                "stale_temp_age_seconds": 3600,
                "max_state_scan_files": 64,
                "retained_quarantine_files": 10,
            }
        ),
        encoding="utf-8",
    )


def test_doctor_help_lists_exact_commands(tmp_path: Path, capsys) -> None:
    handle_doctor_command(tmp_path, "/doctor help")
    output = capsys.readouterr().out

    for command in (
        "/doctor",
        "/doctor help",
        "/doctor trace status",
        "/doctor trace latest",
        "/doctor trace summary",
        "/doctor state status",
        "/doctor state repair",
        "/doctor export",
    ):
        assert command in output


def test_doctor_trace_status_has_no_absolute_path(tmp_path: Path, capsys) -> None:
    _policy(tmp_path)
    handle_doctor_command(tmp_path, "/doctor trace status")
    output = capsys.readouterr().out

    assert "Store path: logs/diagnostics/execution-traces.jsonl" in output
    assert str(tmp_path) not in output


def test_doctor_trace_summary_reports_disabled(tmp_path: Path, monkeypatch, capsys) -> None:
    _policy(tmp_path)
    monkeypatch.delenv("VEGA_EXECUTION_TRACE", raising=False)
    handle_doctor_command(tmp_path, "/doctor trace summary")
    assert capsys.readouterr().out.strip() == "Execution tracing is disabled."


def test_doctor_export_is_explicit_and_rejects_arguments(tmp_path: Path, capsys) -> None:
    _policy(tmp_path)
    handle_doctor_command(tmp_path, "/doctor")
    assert not (tmp_path / "logs" / "diagnostics" / "reports").exists()

    handle_doctor_command(tmp_path, "/doctor export ../../outside")
    output = capsys.readouterr().out
    assert "Unknown doctor command." in output
    assert not (tmp_path / "logs" / "diagnostics" / "reports").exists()

    handle_doctor_command(tmp_path, "/doctor export")
    output = capsys.readouterr().out
    assert "Diagnostics report exported: logs/diagnostics/reports/doctor-" in output
    assert str(tmp_path) not in output
    assert len(list((tmp_path / "logs" / "diagnostics" / "reports").glob("doctor-*.json"))) == 1


def test_unknown_doctor_command_is_safe(tmp_path: Path, capsys) -> None:
    _policy(tmp_path)
    handle_doctor_command(tmp_path, "/doctor surprise")
    output = capsys.readouterr().out
    assert output.startswith("Unknown doctor command.\n")
    assert "TOP-SECRET-DIAGNOSTICS" not in output

