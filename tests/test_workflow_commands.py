import shutil
import tempfile
import unittest
from pathlib import Path

from core.command_handler import handle_workflow_command
from core.command_router import CommandRouter, CommandTarget
from core.intent_router import IntentRouter


class WorkflowCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        shutil.copy(
            Path(__file__).parents[1] / "config" / "checkpoint_policy.json",
            self.root / "config" / "checkpoint_policy.json",
        )

    def test_intent_and_command_routing(self):
        intent = IntentRouter().route('/workflow start feature "Add command"')
        route = CommandRouter().route(intent)
        self.assertEqual(route.target, CommandTarget.WORKFLOW)

    def test_list_command(self):
        result = handle_workflow_command("/workflow list", self.root)
        self.assertIn("feature", result)
        self.assertIn("bugfix", result)
        self.assertIn("refactor", result)

    def test_start_status_cancel_commands(self):
        result = handle_workflow_command('/workflow start feature "Add command"', self.root)
        self.assertIn("waiting_patch", result)
        self.assertIn("waiting_patch", handle_workflow_command("/workflow status", self.root))
        self.assertIn("cancelled", handle_workflow_command("/workflow cancel", self.root))

    def test_existing_command_remains_compatible(self):
        route = CommandRouter().route(IntentRouter().route("/status"))
        self.assertEqual(route.target, CommandTarget.STATUS)


if __name__ == "__main__":
    unittest.main()
