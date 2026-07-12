"""Bugfix coding workflow."""

from workflows.base_workflow import BaseWorkflow


class BugfixWorkflow(BaseWorkflow):
    name = "bugfix"
    step_definitions = (
        ("bug_description", "Record the bug description"),
        ("context", "Collect project context"),
        ("components", "Find related components"),
        ("reproduction", "Record safe reproduction result"),
        ("cause", "Identify the probable cause"),
        ("plan", "Build a minimal fix plan"),
        ("patch", "Validate a real minimal pending patch"),
        ("confirmation", "Wait for explicit confirmation"),
        ("apply", "Apply the confirmed patch"),
        ("verify", "Repeat verification once"),
        ("report", "Finish the process"),
    )

    def analyze_artifacts(self, run):
        context = run.context
        reproduction = context.get("reproduction_result") or {
            "status": "not_available",
            "reason": "No deterministic reproduction command was supplied.",
        }
        probable_cause = context.get("probable_cause") or (
            "Requires inspection of related components before patch preparation."
        )
        return {
            "bug_description": run.task,
            "reproduction_method": context.get("reproduction_method"),
            "reproduction_result": reproduction,
            "related_components": context.get("related_files", []),
            "probable_cause": probable_cause,
        }
