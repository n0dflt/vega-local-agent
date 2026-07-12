"""Context-aware deterministic planning for VEGA coding workflows."""

from __future__ import annotations

from typing import Any


class TaskPlanner:
    """Build a workflow plan from task text and project context."""

    def create_plan(
        self,
        task: str,
        context: dict[str, Any],
        steps: list[str],
        workflow_type: str | None = None,
    ) -> list[str]:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("Task must not be empty.")
        if not isinstance(context, dict):
            raise TypeError("Project context must be a dictionary.")
        if not steps:
            raise ValueError("Workflow steps must not be empty.")

        workflow = workflow_type or str(context.get("workflow") or "coding")
        related = list(context.get("related_files") or [])[:5]
        scope = (
            ", ".join(related)
            if related
            else "discover relevant project files"
        )
        plan = [
            f"Analyze {workflow} task: {task.strip()}",
            f"Use project context to inspect: {scope}",
        ]
        plan.extend(
            f"{index}. {str(step).strip()}"
            for index, step in enumerate(steps, 1)
            if str(step).strip()
        )
        return plan
