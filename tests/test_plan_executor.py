import pytest

from core.execution_plan import (
    ExecutionPlan,
    ToolCallStep,
)
from core.plan_executor import (
    PlanExecutionStatus,
    execute_plan,
)
from core.tool_executor import ToolExecutor


def _plan(
    *steps: ToolCallStep,
) -> ExecutionPlan:
    return ExecutionPlan(
        goal="Test controlled execution",
        steps=tuple(steps),
    )


def test_safe_steps_execute_in_order() -> None:
    calls: list[tuple[str, int]] = []

    def first(value: int) -> dict[str, int]:
        calls.append(("first", value))
        return {"value": value}

    def second(value: int) -> dict[str, int]:
        calls.append(("second", value))
        return {"value": value}

    plan = _plan(
        ToolCallStep(
            step_id=1,
            tool_name="first",
            arguments={"value": 10},
            required_permission="READ",
        ),
        ToolCallStep(
            step_id=2,
            tool_name="second",
            arguments={"value": 20},
            required_permission="DRAFT",
            depends_on=(1,),
        ),
    )

    result = execute_plan(
        plan,
        ToolExecutor(
            {
                "first": first,
                "second": second,
            }
        ),
    )

    assert result.status is (
        PlanExecutionStatus.COMPLETED
    )
    assert result.ok is True
    assert calls == [
        ("first", 10),
        ("second", 20),
    ]
    assert len(result.steps) == 2
    assert all(step.ok for step in result.steps)


def test_unsafe_permission_blocks_entire_plan() -> None:
    calls: list[str] = []

    plan = _plan(
        ToolCallStep(
            step_id=1,
            tool_name="safe",
            required_permission="READ",
        ),
        ToolCallStep(
            step_id=2,
            tool_name="write",
            required_permission="WRITE",
            depends_on=(1,),
        ),
    )

    result = execute_plan(
        plan,
        ToolExecutor(
            {
                "safe": lambda: calls.append("safe"),
                "write": lambda: calls.append("write"),
            }
        ),
    )

    assert result.status is PlanExecutionStatus.BLOCKED
    assert result.blocked_step_id == 2
    assert result.blocked_tool_name == "write"
    assert "WRITE" in result.error
    assert result.steps == ()
    assert calls == []


def test_unknown_later_tool_blocks_before_execution() -> None:
    calls: list[str] = []

    plan = _plan(
        ToolCallStep(
            step_id=1,
            tool_name="known",
            required_permission="READ",
        ),
        ToolCallStep(
            step_id=2,
            tool_name="missing",
            required_permission="READ",
            depends_on=(1,),
        ),
    )

    result = execute_plan(
        plan,
        ToolExecutor(
            {
                "known": lambda: calls.append("known"),
            }
        ),
    )

    assert result.status is PlanExecutionStatus.BLOCKED
    assert result.blocked_step_id == 2
    assert "unregistered tool" in result.error
    assert calls == []


def test_execution_stops_after_first_failure() -> None:
    calls: list[str] = []

    def failing() -> None:
        calls.append("failing")
        raise RuntimeError("controlled failure")

    def later() -> None:
        calls.append("later")

    plan = _plan(
        ToolCallStep(
            step_id=1,
            tool_name="failing",
            required_permission="READ",
        ),
        ToolCallStep(
            step_id=2,
            tool_name="later",
            required_permission="READ",
            depends_on=(1,),
        ),
    )

    result = execute_plan(
        plan,
        ToolExecutor(
            {
                "failing": failing,
                "later": later,
            }
        ),
    )

    assert result.status is PlanExecutionStatus.FAILED
    assert result.blocked_step_id == 1
    assert len(result.steps) == 1
    assert result.steps[0].ok is False
    assert "controlled failure" in result.error
    assert calls == ["failing"]


def test_invalid_arguments_are_reported() -> None:
    def requires_value(value: int) -> int:
        return value

    plan = _plan(
        ToolCallStep(
            step_id=1,
            tool_name="requires_value",
            arguments={},
            required_permission="READ",
        ),
    )

    result = execute_plan(
        plan,
        ToolExecutor(
            {
                "requires_value": requires_value,
            }
        ),
    )

    assert result.status is PlanExecutionStatus.FAILED
    assert result.steps[0].status.value == (
        "invalid_arguments"
    )
    assert "TypeError" in result.error


def test_execution_result_serializes() -> None:
    plan = _plan(
        ToolCallStep(
            step_id=1,
            tool_name="read",
            required_permission="READ",
        ),
    )

    result = execute_plan(
        plan,
        ToolExecutor(
            {
                "read": lambda: {"ok": True},
            }
        ),
    )

    serialized = result.to_dict()

    assert serialized["status"] == "completed"
    assert serialized["steps"][0]["tool_name"] == (
        "read"
    )
    assert serialized["steps"][0]["data"] == {
        "ok": True,
    }


def test_invalid_executor_is_rejected() -> None:
    plan = _plan(
        ToolCallStep(
            step_id=1,
            tool_name="read",
        ),
    )

    with pytest.raises(
        TypeError,
        match="ToolExecutor",
    ):
        execute_plan(plan, object())
