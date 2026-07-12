"""Registry for available VEGA workflows."""

from __future__ import annotations

from workflows.base_workflow import BaseWorkflow
from workflows.models import WorkflowError


class UnknownWorkflowError(WorkflowError):
    pass


class DuplicateWorkflowError(WorkflowError):
    pass


class WorkflowRegistry:
    def __init__(self) -> None:
        self._workflows: dict[str, BaseWorkflow] = {}

    def register(self, workflow: BaseWorkflow) -> None:
        if not isinstance(workflow, BaseWorkflow):
            raise TypeError("workflow must be a BaseWorkflow instance.")
        name = workflow.name.strip().lower()
        if not name:
            raise ValueError("Workflow name must not be empty.")
        if name in self._workflows:
            raise DuplicateWorkflowError(f"Workflow is already registered: {name}.")
        self._workflows[name] = workflow

    def get(self, name: str) -> BaseWorkflow:
        normalized = name.strip().lower()
        try:
            return self._workflows[normalized]
        except KeyError as exc:
            raise UnknownWorkflowError(f"Unknown workflow: {name}.") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._workflows))

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name.strip().lower() in self._workflows
