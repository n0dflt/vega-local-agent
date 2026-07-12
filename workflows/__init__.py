from workflows.coding import BugfixWorkflow, FeatureWorkflow, RefactorWorkflow
from workflows.engine import WorkflowEngine
from workflows.models import WorkflowRun, WorkflowStatus
from workflows.registry import WorkflowRegistry


def default_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    for workflow in (FeatureWorkflow(), BugfixWorkflow(), RefactorWorkflow()):
        registry.register(workflow)
    return registry


__all__ = ["WorkflowEngine", "WorkflowRegistry", "WorkflowRun", "WorkflowStatus", "default_registry"]
