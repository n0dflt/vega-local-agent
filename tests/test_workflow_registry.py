import unittest

from workflows import default_registry
from workflows.coding import FeatureWorkflow
from workflows.registry import DuplicateWorkflowError, UnknownWorkflowError, WorkflowRegistry


class WorkflowRegistryTests(unittest.TestCase):
    def test_three_workflows_are_registered(self):
        self.assertEqual(default_registry().names(), ("bugfix", "feature", "refactor"))

    def test_unknown_workflow_is_rejected(self):
        with self.assertRaises(UnknownWorkflowError):
            default_registry().get("missing")

    def test_duplicate_registration_is_rejected(self):
        registry = WorkflowRegistry()
        registry.register(FeatureWorkflow())
        with self.assertRaises(DuplicateWorkflowError):
            registry.register(FeatureWorkflow())


if __name__ == "__main__":
    unittest.main()
