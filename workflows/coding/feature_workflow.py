"""Feature coding workflow."""

from workflows.base_workflow import BaseWorkflow


class FeatureWorkflow(BaseWorkflow):
    name = "feature"
    step_definitions = (
        ("goal", "Define the feature goal"),
        ("context", "Collect project context"),
        ("affected_files", "Find related files, tests, and documentation"),
        ("plan", "Build an implementation plan"),
        ("patch", "Validate a real pending patch"),
        ("confirmation", "Wait for explicit confirmation"),
        ("apply", "Apply the confirmed patch"),
        ("verify", "Run verification once"),
        ("report", "Build the final result"),
    )

    def analyze_artifacts(self, run):
        return {
            "goal": run.task,
            "context": run.context,
            "affected_files": run.context.get("related_files", []),
            "tests": run.context.get("tests", []),
            "documentation": run.context.get("documentation", []),
        }
