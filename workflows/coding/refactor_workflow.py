"""Behavior-preserving refactor workflow."""

from workflows.base_workflow import BaseWorkflow
from workflows.models import WorkflowError


class RefactorWorkflow(BaseWorkflow):
    name = "refactor"
    step_definitions = (
        ("boundaries", "Define refactoring boundaries"),
        ("behavior", "Record current behavior"),
        ("dependencies", "Find dependencies"),
        ("tests", "Find related tests"),
        ("plan", "Build a structural plan"),
        ("patch", "Validate a behavior-preserving patch"),
        ("confirmation", "Wait for explicit confirmation"),
        ("apply", "Apply the confirmed patch"),
        ("verify", "Run regression verification"),
        ("report", "Build the final result"),
    )

    def validate_scope(self, run):
        text = run.task.lower()
        feature_words = (
            "add ",
            "new feature",
            "implement ",
            "добав",
            "новая функц",
            "реализ",
        )
        if any(word in text for word in feature_words):
            run.artifacts["mixed_scope_detected"] = True
            raise WorkflowError(
                "Refactor request also contains feature scope; "
                "choose feature or split the task."
            )

    def analyze_artifacts(self, run):
        context = run.context
        return {
            "boundaries": context.get("related_files", []),
            "current_behavior": context.get("current_behavior")
            or "Must be preserved by the pending patch.",
            "dependencies": context.get("dependencies", []),
            "related_tests": context.get("tests", []),
            "structural_change": run.task,
            "behavior_preservation_required": True,
        }
