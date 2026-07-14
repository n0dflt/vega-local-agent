import pytest

from core.execution_progress import ExecutionProgressStage
from core.execution_plan import (
    ExecutionPlan,
    ToolCallStep,
)
from core.plan_executor import (
    PlanExecutionStatus,
    StepExecutionObservation,
    execute_plan,
)
from core.tool_executor import (
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolExecutor,
)
from core.tool_confirmation import ToolConfirmationManager
from permissions import (
    PermissionCapability,
    PermissionEffect,
    PermissionEvaluator,
    PermissionPolicy,
    PermissionRisk,
    PermissionRule,
)


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
    assert result.error == "step 1 failed: Tool execution failed."
    assert result.steps[0].error_code == "tool_execution_failed"
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
    assert result.error == "step 1 failed: Tool arguments are invalid."
    assert result.steps[0].error_code == "invalid_arguments"


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



def test_tool_reported_failure_stops_plan() -> None:
    calls: list[str] = []

    def reported_failure() -> dict[str, object]:
        calls.append("failure")
        return {
            "ok": False,
            "error": "file could not be read",
            "data": None,
        }

    def later() -> None:
        calls.append("later")

    plan = _plan(
        ToolCallStep(
            step_id=1,
            tool_name="reported_failure",
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
                "reported_failure": reported_failure,
                "later": later,
            }
        ),
    )

    assert result.status is PlanExecutionStatus.FAILED
    assert result.blocked_step_id == 1
    assert result.steps[0].error_code == (
        "tool_reported_failure"
    )
    assert result.error == "step 1 failed: Tool reported an unsuccessful result."
    assert "file could not be read" not in repr(result)
    assert calls == ["failure"]

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


def test_step_observer_receives_only_safe_metadata() -> None:
    observations: list[StepExecutionObservation] = []
    calls: list[dict[str, str]] = []
    plan = _plan(
        ToolCallStep(
            step_id=1,
            tool_name="read",
            arguments={"secret": "TOP-SECRET-TRACE"},
            required_permission="READ",
        ),
    )

    result = execute_plan(
        plan,
        ToolExecutor({"read": lambda secret: calls.append({"secret": secret})}),
        risk_by_tool={"read": "low"},
        step_observer=observations.append,
    )

    assert result.ok
    assert calls == [{"secret": "TOP-SECRET-TRACE"}]
    assert observations == [
        StepExecutionObservation(1, "read", "READ", "low", "success", "")
    ]
    assert "TOP-SECRET-TRACE" not in repr(observations)


def test_step_observer_failure_does_not_change_execution() -> None:
    calls: list[str] = []
    plan = _plan(ToolCallStep(1, "read", required_permission="READ"))

    def observer(observation: StepExecutionObservation) -> None:
        raise RuntimeError("observer failed")

    result = execute_plan(
        plan,
        ToolExecutor({"read": lambda: calls.append("read")}),
        step_observer=observer,
    )

    assert result.ok
    assert calls == ["read"]


def test_step_observer_sanitizes_untrusted_diagnostic_values() -> None:
    observations: list[StepExecutionObservation] = []
    plan = _plan(ToolCallStep(1, "read", required_permission="READ"))
    executor = ToolExecutor({"read": lambda: None})

    def unsafe_result(request):
        return ToolExecutionResult(
            ToolExecutionStatus.FAILED,
            request.tool_name,
            error="TOP-SECRET-TRACE",
            error_code="TOP-SECRET-CODE",
        )

    executor.execute = unsafe_result
    result = execute_plan(
        plan,
        executor,
        risk_by_tool={"read": "TOP-SECRET-RISK"},
        step_observer=observations.append,
    )

    assert not result.ok
    assert observations == [
        StepExecutionObservation(
            1,
            "read",
            "READ",
            "",
            "failed",
            "tool_execution_failed",
        )
    ]
    assert "TOP-SECRET" not in repr(observations)


def test_unexpected_executor_exception_fails_once_with_safe_code() -> None:
    calls: list[str] = []
    plan = _plan(ToolCallStep(1, "read", required_permission="READ"))
    executor = ToolExecutor({"read": lambda: None})

    def raises(request):
        calls.append(request.tool_name)
        raise RuntimeError("TOP-SECRET-TRACE")

    executor.execute = raises
    result = execute_plan(plan, executor)

    assert result.status is PlanExecutionStatus.FAILED
    assert calls == ["read"]
    assert result.steps[0].error_code == "tool_execution_failed"
    assert "TOP-SECRET-TRACE" not in repr(result)


def test_progress_events_follow_real_execution_once() -> None:
    calls: list[str] = []
    events = []
    plan = _plan(
        ToolCallStep(
            1,
            "read",
            required_permission="READ",
            description="Read project",
        )
    )

    result = execute_plan(
        plan,
        ToolExecutor({"read": lambda: calls.append("read")}),
        progress_callback=events.append,
    )

    assert result.ok
    assert calls == ["read"]
    assert [event.stage for event in events] == [
        ExecutionProgressStage.PLAN_READY,
        ExecutionProgressStage.STEP_RUNNING,
        ExecutionProgressStage.STEP_COMPLETED,
    ]
    assert all("arguments" not in repr(event) for event in events)


def _confirmed_executor(registry) -> ToolExecutor:
    rules = tuple(
        PermissionRule(
            name,
            (PermissionCapability.PROCESS_EXECUTE,),
            PermissionRisk.HIGH,
            PermissionEffect.CONFIRM,
            False,
            "Runs a bounded diagnostic command.",
        )
        for name in registry
    )
    policy = PermissionPolicy(
        1,
        PermissionEffect.DENY,
        "CONFIRM",
        10,
        rules,
    )
    return ToolExecutor(registry, PermissionEvaluator(policy))


def test_confirmed_execute_steps_use_existing_one_time_confirmation() -> None:
    calls: list[str] = []
    prompts: list[str] = []
    executor = _confirmed_executor(
        {
            "tests": lambda: calls.append("tests") or {"ok": True},
            "compile": lambda: calls.append("compile") or {"ok": True},
        }
    )
    plan = _plan(
        ToolCallStep(1, "tests", required_permission="EXECUTE"),
        ToolCallStep(
            2,
            "compile",
            required_permission="EXECUTE",
            depends_on=(1,),
        ),
    )

    result = execute_plan(
        plan,
        executor,
        confirmation_permissions=("EXECUTE",),
        confirmation_manager=ToolConfirmationManager(
            lambda prompt: prompts.append(prompt) or "yes"
        ),
    )

    assert result.status is PlanExecutionStatus.COMPLETED
    assert calls == ["tests", "compile"]
    assert len(prompts) == 2


def test_progress_callback_failure_never_repeats_tool() -> None:
    calls: list[str] = []
    plan = _plan(ToolCallStep(1, "read", required_permission="READ"))

    def broken_progress(event) -> None:
        raise RuntimeError("renderer failed")

    result = execute_plan(
        plan,
        ToolExecutor({"read": lambda: calls.append("read")}),
        progress_callback=broken_progress,
    )

    assert result.ok
    assert calls == ["read"]


def test_confirmation_progress_is_not_step_completion() -> None:
    events = []
    calls: list[str] = []
    plan = _plan(
        ToolCallStep(
            1,
            "write",
            required_permission="WRITE",
            description="Update file",
        )
    )

    result = execute_plan(
        plan,
        ToolExecutor({"write": lambda: calls.append("write")}),
        progress_callback=events.append,
    )

    assert result.status is PlanExecutionStatus.BLOCKED
    assert calls == []
    assert [event.stage for event in events] == [
        ExecutionProgressStage.PLAN_READY,
        ExecutionProgressStage.AWAITING_CONFIRMATION,
    ]
