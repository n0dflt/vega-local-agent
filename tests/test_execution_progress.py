from dataclasses import FrozenInstanceError, fields

import pytest

from core.execution_progress import (
    ExecutionProgressError,
    ExecutionProgressEvent,
    ExecutionProgressStage,
    safe_progress_title,
)


def test_valid_step_event_is_immutable() -> None:
    event = ExecutionProgressEvent(
        stage=ExecutionProgressStage.STEP_RUNNING,
        current_step=2,
        total_steps=5,
        title="Анализ кода",
    )

    assert event.current_step == 2
    assert event.title == "Анализ кода"
    with pytest.raises(FrozenInstanceError):
        event.title = "changed"


@pytest.mark.parametrize(
    ("current", "total"),
    [(-1, 1), (0, -1), (2, 1)],
)
def test_invalid_step_counts_are_rejected(current: int, total: int) -> None:
    with pytest.raises(ExecutionProgressError):
        ExecutionProgressEvent(
            stage=ExecutionProgressStage.COMPLETED,
            current_step=current,
            total_steps=total,
        )


def test_empty_plan_can_complete() -> None:
    event = ExecutionProgressEvent(
        stage=ExecutionProgressStage.COMPLETED,
        current_step=0,
        total_steps=0,
        elapsed_seconds=0,
    )

    assert event.total_steps == 0
    assert event.elapsed_seconds == 0.0


def test_step_stage_requires_a_real_plan() -> None:
    with pytest.raises(ExecutionProgressError, match="non-empty plan"):
        ExecutionProgressEvent(stage=ExecutionProgressStage.STEP_RUNNING)


def test_plan_ready_requires_exact_safe_titles() -> None:
    event = ExecutionProgressEvent(
        stage=ExecutionProgressStage.PLAN_READY,
        total_steps=2,
        plan_titles=("  Inspect\nproject  ", "Run tests"),
    )

    assert event.plan_titles == ("Inspect project", "Run tests")
    with pytest.raises(ExecutionProgressError, match="match plan titles"):
        ExecutionProgressEvent(
            stage=ExecutionProgressStage.PLAN_READY,
            total_steps=1,
            plan_titles=(),
        )


def test_public_model_has_no_payload_or_exception_fields() -> None:
    names = {item.name for item in fields(ExecutionProgressEvent)}

    assert "arguments" not in names
    assert "payload" not in names
    assert "exception" not in names


def test_title_removes_controls_and_endpoint_term() -> None:
    title = safe_progress_title("\x1b[31mCall endpoint\nnow\x00")

    assert title == "[31mCall operation now"
    assert "endpoint" not in title.lower()


def test_events_do_not_share_mutable_request_state() -> None:
    first = ExecutionProgressEvent(
        stage=ExecutionProgressStage.PLAN_READY,
        total_steps=1,
        plan_titles=("One",),
    )
    second = ExecutionProgressEvent(
        stage=ExecutionProgressStage.PLAN_READY,
        total_steps=1,
        plan_titles=("Two",),
    )

    assert first.plan_titles == ("One",)
    assert second.plan_titles == ("Two",)
