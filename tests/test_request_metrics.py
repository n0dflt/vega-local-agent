import json
from datetime import datetime, timedelta, timezone
from threading import Thread
from types import SimpleNamespace

from core.agent_runtime import append_request_metrics, append_tool_diagnostics
from core.request_metrics import (
    RequestMetrics,
    RequestPhase,
    RequestStatus,
    TokenUsage,
)
from ui.request_summary import (
    format_duration,
    format_request_summary,
    format_token_count,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.base = datetime(2026, 7, 14, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self.value

    def wall(self) -> datetime:
        return self.base + timedelta(seconds=self.value)

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _metrics(clock: FakeClock) -> RequestMetrics:
    return RequestMetrics(clock=clock.monotonic, wall_clock=clock.wall)


def test_timer_starts_updates_stops_and_records_phases() -> None:
    clock = FakeClock()
    metrics = _metrics(clock)

    assert metrics.running
    assert metrics.elapsed_seconds == 0
    clock.advance(2)
    assert metrics.elapsed_seconds == 2
    metrics.mark_phase(RequestPhase.MODEL_WAIT)
    clock.advance(3)
    metrics.mark_phase(RequestPhase.RESPONSE_PROCESSING)
    clock.advance(1)
    snapshot = metrics.stop(RequestStatus.COMPLETED)

    assert not metrics.running
    assert snapshot.duration_seconds == 6
    assert metrics.elapsed_seconds == 6
    assert dict(snapshot.phase_durations) == {
        "preparing": 2,
        "model_wait": 3,
        "response_processing": 1,
    }
    clock.advance(20)
    assert metrics.elapsed_seconds == 6
    assert metrics.stop(RequestStatus.FAILED) is snapshot


def test_duration_and_locale_number_formatting() -> None:
    assert format_duration(42) == "42 сек."
    assert format_duration(198) == "3 мин. 18 сек."
    assert format_duration(9012) == "2 ч. 30 мин. 12 сек."
    assert format_token_count(112132) == "112 132"
    assert format_token_count(112132, unicode=False) == "112,132"


def test_exact_usage_is_aggregated_across_model_calls() -> None:
    clock = FakeClock()
    metrics = _metrics(clock)
    metrics.record_usage(TokenUsage(90000, 20000))
    metrics.record_usage(TokenUsage(500, 1632))
    snapshot = metrics.stop(RequestStatus.COMPLETED)

    assert snapshot.token_usage == TokenUsage(90500, 21632)
    summary = format_request_summary(snapshot)
    assert summary == (
        "Решено за 0 сек. Использовано 112 132 токенов: "
        "90 500 входных и 21 632 выходных."
    )


def test_any_missing_usage_keeps_request_usage_unavailable() -> None:
    clock = FakeClock()
    metrics = _metrics(clock)
    metrics.record_usage(TokenUsage(12, 8))
    metrics.record_usage(None)
    clock.advance(72)
    snapshot = metrics.stop(RequestStatus.FAILED)

    assert snapshot.token_usage is None
    summary = format_request_summary(snapshot)
    assert summary == (
        "Обработка остановлена через 1 мин. 12 сек. "
        "Данные об использовании токенов недоступны."
    )
    assert "0 токен" not in summary


def test_cancel_timeout_and_new_request_reset() -> None:
    first_clock = FakeClock()
    first = _metrics(first_clock)
    first.record_usage(TokenUsage(4, 2))
    first_clock.advance(9)
    cancelled = first.stop(RequestStatus.CANCELLED)

    second_clock = FakeClock()
    second = _metrics(second_clock)
    second_clock.advance(5)
    timed_out = second.stop(RequestStatus.TIMED_OUT)

    assert cancelled.duration_seconds == 9
    assert cancelled.token_usage == TokenUsage(4, 2)
    assert timed_out.duration_seconds == 5
    assert timed_out.token_usage is None
    assert format_request_summary(timed_out).startswith(
        "Превышен тайм-аут через 5 сек."
    )


def test_parallel_requests_keep_independent_metrics() -> None:
    clocks = [FakeClock(), FakeClock()]
    trackers = [_metrics(clock) for clock in clocks]
    snapshots = [None, None]

    def complete(index: int, seconds: int, usage: TokenUsage) -> None:
        clocks[index].advance(seconds)
        trackers[index].record_usage(usage)
        snapshots[index] = trackers[index].stop(RequestStatus.COMPLETED)

    threads = [
        Thread(target=complete, args=(0, 3, TokenUsage(10, 2))),
        Thread(target=complete, args=(1, 8, TokenUsage(20, 5))),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert snapshots[0].duration_seconds == 3
    assert snapshots[0].token_usage == TokenUsage(10, 2)
    assert snapshots[1].duration_seconds == 8
    assert snapshots[1].token_usage == TokenUsage(20, 5)


def test_log_record_contains_metadata_but_no_request_content() -> None:
    clock = FakeClock()
    metrics = _metrics(clock)
    metrics.record_usage(TokenUsage(100, 25))
    clock.advance(1.25)
    record = metrics.stop(RequestStatus.COMPLETED).to_log_record()

    assert record["duration_seconds"] == 1.25
    assert record["input_tokens"] == 100
    assert record["output_tokens"] == 25
    assert record["total_tokens"] == 125
    assert record["status"] == "completed"
    assert "prompt" not in record
    assert "response" not in record


def test_session_log_receives_structured_request_metrics(tmp_path) -> None:
    clock = FakeClock()
    metrics = _metrics(clock)
    metrics.record_usage(TokenUsage(7, 3))
    clock.advance(4)
    snapshot = metrics.stop(RequestStatus.COMPLETED)
    log_file = tmp_path / "session.txt"
    log_file.write_text("VEGA session log\n", encoding="utf-8")

    append_request_metrics(log_file, snapshot)

    lines = log_file.read_text(encoding="utf-8").splitlines()
    section_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("[REQUEST_METRICS]")
    )
    record = json.loads(lines[section_index + 1])
    assert record["status"] == "completed"
    assert record["input_tokens"] == 7
    assert record["output_tokens"] == 3
    assert record["total_tokens"] == 10


def test_session_log_receives_safe_tool_diagnostics(tmp_path) -> None:
    log_file = tmp_path / "session.txt"
    log_file.write_text("VEGA session log\n", encoding="utf-8")
    diagnostics = {
        "tool": "test_run",
        "command_id": "tests",
        "group_id": "all",
        "resolved_executable": "python-runtime",
        "cwd": str(tmp_path),
        "returncode": 0,
        "timed_out": False,
        "duration_ms": 100,
        "timeout_seconds": 180,
        "stdout_summary": {"chars": 20, "pytest_counts": {"passed": 1}},
        "stderr_summary": {"chars": 0},
        "reason_code": "",
        "stdout": "TOP-SECRET-OUTPUT",
    }
    execution_result = SimpleNamespace(
        steps=(
            SimpleNamespace(
                data={"data": {"diagnostics": diagnostics}},
            ),
        ),
    )

    append_tool_diagnostics(log_file, execution_result)

    text = log_file.read_text(encoding="utf-8")
    assert "[TOOL_DIAGNOSTICS]" in text
    assert '"tool": "test_run"' in text
    assert '"returncode": 0' in text
    assert "TOP-SECRET-OUTPUT" not in text
