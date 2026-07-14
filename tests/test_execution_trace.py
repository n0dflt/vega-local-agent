from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from core.execution_trace import (
    ExecutionTrace,
    MAX_IDENTIFIER_CHARS,
    MAX_TRACE_COLLECTION_ITEMS,
    MAX_TRACE_FILE_BYTES,
    TRACE_RELATIVE_PATH,
    TraceError,
    TraceLifecycleError,
    TraceRecorder,
    TraceSerializationError,
    TraceStatus,
    TraceStep,
    append_trace,
    load_latest_trace,
    safe_trace_error_code,
    serialize_trace,
    scan_trace_store,
    trace_persistence_enabled,
)
from core.agent_runtime import handle_doctor_command


def _trace(status: TraceStatus = TraceStatus.COMPLETED) -> ExecutionTrace:
    recorder = TraceRecorder()
    recorder.record_route(
        intent="project_search",
        domain="coding",
        required_capabilities=("project.search",),
        selected_tools=("search_in_files",),
        confirmation_required=False,
    )
    recorder.record_permissions(("automatic",))
    recorder.record_model(
        profile="code",
        model="qwen2.5-coder:14b",
        reason_code="intent_profile",
        fallback_used=False,
    )
    recorder.record_context_budget(
        {
            "original_chars": 100,
            "selected_chars": 80,
            "max_chars": 80,
            "truncated": True,
        }
    )
    recorder.record_step(
        TraceStep(1, "search_in_files", "READ", "low", "success")
    )
    return recorder.finalize(status)


def test_trace_is_immutable_after_finalize() -> None:
    trace = _trace()

    with pytest.raises(FrozenInstanceError):
        trace.status = TraceStatus.FAILED
    with pytest.raises(TypeError):
        trace.context_budget["max_chars"] = 1


def test_recorder_clears_request_local_state_after_finalize() -> None:
    recorder = TraceRecorder()
    recorder.record_route(
        intent="project_search",
        domain="coding",
        required_capabilities=("project.search",),
        selected_tools=("search_in_files",),
        confirmation_required=False,
    )
    recorder.record_step(
        TraceStep(1, "search_in_files", "READ", "low", "success")
    )

    trace = recorder.finalize(TraceStatus.COMPLETED)

    assert trace.intent == "project_search"
    assert recorder._trace_id == ""
    assert recorder._intent == ""
    assert recorder._selected_tools == ()
    assert recorder._steps == []
    assert recorder._error_codes == []
    with pytest.raises(AttributeError):
        recorder.handler = object()


def test_second_finalize_is_rejected() -> None:
    recorder = TraceRecorder()
    recorder.finalize(TraceStatus.COMPLETED)

    with pytest.raises(TraceLifecycleError):
        recorder.finalize(TraceStatus.FAILED)
    with pytest.raises(TraceLifecycleError):
        recorder.record_permissions(("automatic",))


@pytest.mark.parametrize(
    "status",
    (TraceStatus.COMPLETED, TraceStatus.BLOCKED, TraceStatus.FAILED),
)
def test_trace_lifecycle_statuses(status: TraceStatus) -> None:
    assert TraceRecorder().finalize(status).status is status


def test_illegal_terminal_transition_is_rejected() -> None:
    with pytest.raises(TraceLifecycleError):
        TraceRecorder().finalize(TraceStatus.STARTED)


def test_safe_serialization_omits_sensitive_values() -> None:
    sentinels = (
        "TOP-SECRET-TRACE",
        "CONFIRMATION-TOKEN-SECRET",
        "SYSTEM-PROMPT-SECRET",
        "EVIDENCE-CONTENT-SECRET",
        r"C:\Users\Secret\private.txt",
        "https://example.com/path?token=SECRET",
    )
    trace = _trace()
    rendered = repr(trace) + repr(trace.to_safe_dict()) + serialize_trace(trace)

    assert all(value not in rendered for value in sentinels)


def test_safe_serialization_uses_allowlisted_fields_only() -> None:
    serialized = serialize_trace(_trace())
    value = json.loads(serialized)

    assert set(value) == {
        "trace_id",
        "request_type",
        "intent",
        "domain",
        "required_capabilities",
        "selected_tools",
        "permission_outcomes",
        "confirmation_required",
        "model_profile",
        "model",
        "model_reason_code",
        "fallback_used",
        "context_budget",
        "steps",
        "status",
        "error_codes",
    }
    assert set(value["steps"][0]) == {
        "step_id",
        "tool_name",
        "permission",
        "risk",
        "status",
        "error_code",
    }


def test_trace_size_limit_fails_closed() -> None:
    with pytest.raises(TraceSerializationError):
        serialize_trace(_trace(), max_chars=10)


def test_trace_step_count_is_bounded() -> None:
    steps = tuple(
        TraceStep(index, f"tool_{index}", "READ", "low", "success")
        for index in range(1, 9)
    ) + (TraceStep(8, "tool_extra", "READ", "low", "success"),)

    with pytest.raises(TraceError, match="at most 8"):
        ExecutionTrace("trace", "contextual", steps=steps)


def test_trace_identifier_lengths_are_bounded() -> None:
    with pytest.raises(TraceError, match="at most"):
        ExecutionTrace("x" * (MAX_IDENTIFIER_CHARS + 1), "contextual")


@pytest.mark.parametrize(
    "field",
    (
        "required_capabilities",
        "selected_tools",
        "permission_outcomes",
        "error_codes",
    ),
)
def test_trace_collections_are_bounded(field: str) -> None:
    values = tuple("tool_execution_failed" for _ in range(MAX_TRACE_COLLECTION_ITEMS + 1))
    if field != "error_codes":
        values = tuple(f"value_{index}" for index in range(MAX_TRACE_COLLECTION_ITEMS + 1))

    with pytest.raises(TraceError, match="at most 8"):
        ExecutionTrace("trace", "contextual", **{field: values})


def test_untrusted_error_codes_fail_closed_to_fixed_vocabulary() -> None:
    secret = "TOP-SECRET-CODE"

    assert safe_trace_error_code(secret, fallback="tool_execution_failed") == (
        "tool_execution_failed"
    )
    with pytest.raises(TraceError, match="allowlisted"):
        TraceStep(1, "read_file", "READ", "low", "failed", secret)
    with pytest.raises(TraceError, match="allowlisted"):
        ExecutionTrace(
            "trace",
            "contextual",
            model_reason_code="secret_reason",
        )


def test_trace_persistence_is_disabled_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("VEGA_EXECUTION_TRACE", raising=False)

    assert not trace_persistence_enabled()
    assert append_trace(tmp_path, _trace()) is None
    assert not (tmp_path / "logs").exists()


@pytest.mark.parametrize("value", ("1", "true", "YES", " on "))
def test_trace_persistence_is_opt_in(value: str, monkeypatch) -> None:
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", value)
    assert trace_persistence_enabled()


def test_trace_file_is_utf8_jsonl(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    path = append_trace(tmp_path, _trace())

    assert path == tmp_path / TRACE_RELATIVE_PATH
    content = path.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert json.loads(content)["status"] == "completed"


def test_trace_rotation_is_bounded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    path = tmp_path / TRACE_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * MAX_TRACE_FILE_BYTES)

    assert append_trace(tmp_path, _trace()) == path
    assert path.stat().st_size < MAX_TRACE_FILE_BYTES
    assert path.with_name(path.name + ".1").stat().st_size == MAX_TRACE_FILE_BYTES


def test_trace_rotation_retains_three_ordered_backups(tmp_path: Path, monkeypatch) -> None:
    from core.runtime_diagnostics import DiagnosticsPolicy

    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    policy = replace(
        DiagnosticsPolicy.defaults(tmp_path),
        max_trace_file_bytes=1024,
        max_trace_records=10,
    )
    path = tmp_path / policy.trace_store_path
    path.parent.mkdir(parents=True)
    for marker in (b"oldest", b"older", b"newer", b"active"):
        path.write_bytes(marker + b"x" * 1018)
        append_trace(tmp_path, _trace(), policy)

    assert path.with_name(path.name + ".1").read_bytes().startswith(b"active")
    assert path.with_name(path.name + ".2").read_bytes().startswith(b"newer")
    assert path.with_name(path.name + ".3").read_bytes().startswith(b"older")


def test_latest_trace_reads_valid_backup_after_corrupt_active(tmp_path: Path, monkeypatch) -> None:
    from core.runtime_diagnostics import DiagnosticsPolicy

    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    policy = DiagnosticsPolicy.defaults(tmp_path)
    path = tmp_path / policy.trace_store_path
    path.parent.mkdir(parents=True)
    path.with_name(path.name + ".1").write_text(serialize_trace(_trace()) + "\n", encoding="utf-8")
    path.write_text("{corrupt\n", encoding="utf-8")

    scan = scan_trace_store(tmp_path, policy)
    assert scan.traces[0].status is TraceStatus.COMPLETED
    assert scan.invalid_records == 1


def test_rotation_failure_does_not_escape(tmp_path: Path, monkeypatch) -> None:
    from core.runtime_diagnostics import DiagnosticsPolicy

    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    policy = replace(DiagnosticsPolicy.defaults(tmp_path), max_trace_file_bytes=1024)
    path = tmp_path / policy.trace_store_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * 1024)
    monkeypatch.setattr(Path, "replace", lambda self, target: (_ for _ in ()).throw(OSError()))

    assert append_trace(tmp_path, _trace(), policy) is None


def test_latest_trace_returns_last_valid_record(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    append_trace(tmp_path, _trace(TraceStatus.COMPLETED))
    append_trace(tmp_path, _trace(TraceStatus.BLOCKED))

    assert load_latest_trace(tmp_path).status is TraceStatus.BLOCKED


def test_latest_trace_handles_corrupt_last_record(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    path = append_trace(tmp_path, _trace())
    with path.open("a", encoding="utf-8") as stream:
        stream.write("{corrupt\n")

    assert load_latest_trace(tmp_path).status is TraceStatus.COMPLETED


def test_unknown_exception_text_is_not_serialized() -> None:
    secret = "TOP-SECRET-TRACE"
    recorder = TraceRecorder()
    try:
        raise RuntimeError(secret)
    except RuntimeError as exc:
        trace = recorder.finalize(
            TraceStatus.FAILED,
            error_codes=("tool_execution_failed",),
        )

    assert "tool_execution_failed" in trace.error_codes
    assert secret not in serialize_trace(trace)


def test_doctor_trace_latest_uses_safe_summary(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    append_trace(tmp_path, _trace())

    handle_doctor_command(tmp_path, "/doctor trace latest")
    output = capsys.readouterr().out

    assert "Trace status: completed" in output
    assert "Selected tools: search_in_files" in output
    assert str(tmp_path) not in output
    assert "TOP-SECRET-TRACE" not in output


def test_doctor_trace_latest_reports_disabled(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv("VEGA_EXECUTION_TRACE", raising=False)

    handle_doctor_command(tmp_path, "/doctor trace latest")

    assert capsys.readouterr().out.strip() == "Execution tracing is disabled."
