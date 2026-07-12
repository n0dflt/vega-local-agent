"""Executable workflow definitions and shared services."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any,Protocol
from workflows.models import WorkflowRun,WorkflowStep


class Planner(Protocol):
    def create_plan(
        self,
        task: str,
        context: dict[str, Any],
        steps: list[str],
        workflow_type: str | None = None,
    ) -> list[str]: ...


@dataclass(slots=True)
class WorkflowServices:
    project_root: Path
    planner: Planner
    project_context: Any
    patch_tools: Any
    test_tools: Any
    task_adapter: Any = None


class BaseWorkflow:
    name = "base"
    step_definitions: tuple[tuple[str, str], ...] = ()

    def create_run(self, task: str) -> WorkflowRun:
        steps = [
            WorkflowStep(step_id, name)
            for step_id, name in self.step_definitions
        ]
        return WorkflowRun.create(self.name, task, steps)

    def collect_context(
        self,
        run: WorkflowRun,
        services: WorkflowServices,
    ) -> dict[str, Any]:
        return services.project_context.collect(run.task, self.name)

    def analyze_artifacts(self, run: WorkflowRun) -> dict[str, Any]:
        return {
            "goal": run.task,
            "affected_files": list(run.context.get("related_files") or []),
        }

    def plan(
        self,
        run: WorkflowRun,
        services: WorkflowServices,
    ) -> list[str]:
        names = [step.name for step in run.steps]
        return services.planner.create_plan(
            run.task,
            run.context,
            names,
            self.name,
        )

    def prepare_patch(
        self,
        run: WorkflowRun,
        services: WorkflowServices,
    ) -> dict[str, Any]:
        return services.patch_tools.prepare(run)

    def apply_patch(
        self,
        run: WorkflowRun,
        services: WorkflowServices,
    ) -> dict[str, Any]:
        return services.patch_tools.apply((run.patch or {}).get("patch_id"),confirmed=True)

    def verify(
        self,
        run: WorkflowRun,
        services: WorkflowServices,
    ) -> dict[str, Any]:
        return services.test_tools.run_once(run)
    def validate_scope(self, run: WorkflowRun) -> None:
        del run
