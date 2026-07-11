import unittest
from unittest.mock import patch

from tools.registry import get_tool
from tools.test_tools import (
    list_test_groups,
    run_test_group,
)


class TestToolsTests(unittest.TestCase):
    @patch("tools.test_tools.list_allowed_commands")
    def test_list_test_groups(self, list_allowed_commands):
        list_allowed_commands.return_value = {
            "ok": True,
            "error": None,
            "data": [
                {"id": "tests", "enabled": True},
                {"id": "tests-terminal", "enabled": True},
                {"id": "tests-terminal-tools", "enabled": True},
                {"id": "tests-terminal-commands", "enabled": True},
            ],
        }

        result = list_test_groups()

        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(len(result["data"]), 4)
        self.assertTrue(
            all(item["available"] for item in result["data"])
        )
        self.assertTrue(
            all(item["enabled"] for item in result["data"])
        )

    @patch("tools.test_tools.list_allowed_commands")
    def test_missing_test_command_is_reported(
        self,
        list_allowed_commands,
    ):
        list_allowed_commands.return_value = {
            "ok": True,
            "error": None,
            "data": [
                {"id": "tests", "enabled": True},
            ],
        }

        result = list_test_groups()

        terminal_group = next(
            item
            for item in result["data"]
            if item["id"] == "terminal"
        )

        self.assertFalse(terminal_group["available"])
        self.assertFalse(terminal_group["enabled"])

    @patch("tools.test_tools.list_allowed_commands")
    def test_policy_error_is_controlled(
        self,
        list_allowed_commands,
    ):
        list_allowed_commands.return_value = {
            "ok": False,
            "error": "Terminal policy file was not found.",
            "data": None,
        }

        result = list_test_groups()

        self.assertFalse(result["ok"])
        self.assertIn(
            "Test command policy could not be loaded",
            result["error"],
        )

    @patch("tools.test_tools.run_allowed_command")
    def test_successful_test_group(
        self,
        run_allowed_command,
    ):
        run_allowed_command.return_value = {
            "ok": True,
            "error": None,
            "data": {
                "command_id": "tests-terminal",
                "stdout": "18 passed\n",
                "stderr": "",
                "returncode": 0,
                "timed_out": False,
                "truncated": False,
                "duration_ms": 100,
                "warning": None,
            },
        }

        result = run_test_group("terminal")

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["data"]["group_id"],
            "terminal",
        )
        self.assertEqual(
            result["data"]["command_id"],
            "tests-terminal",
        )
        self.assertIn(
            "18 passed",
            result["data"]["stdout"],
        )

    @patch("tools.test_tools.run_allowed_command")
    def test_failed_test_group_preserves_output(
        self,
        run_allowed_command,
    ):
        run_allowed_command.return_value = {
            "ok": False,
            "error": None,
            "data": {
                "command_id": "tests",
                "stdout": "1 failed\n",
                "stderr": "",
                "returncode": 1,
                "timed_out": False,
                "truncated": False,
                "duration_ms": 100,
                "warning": None,
            },
        }

        result = run_test_group("all")

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["data"]["returncode"],
            1,
        )
        self.assertIn(
            "1 failed",
            result["data"]["stdout"],
        )

    @patch("tools.test_tools.run_allowed_command")
    def test_command_start_error_is_controlled(
        self,
        run_allowed_command,
    ):
        run_allowed_command.return_value = {
            "ok": False,
            "error": "Test command could not be started.",
            "data": None,
        }

        result = run_test_group("all")

        self.assertFalse(result["ok"])
        self.assertIn(
            "could not be started",
            result["error"],
        )

    @patch("tools.test_tools.run_allowed_command")
    def test_unknown_group_does_not_execute(
        self,
        run_allowed_command,
    ):
        result = run_test_group("unknown")

        self.assertFalse(result["ok"])
        self.assertIn(
            "Unknown test group",
            result["error"],
        )
        run_allowed_command.assert_not_called()

    @patch("tools.test_tools.run_allowed_command")
    def test_arbitrary_arguments_are_rejected(
        self,
        run_allowed_command,
    ):
        result = run_test_group("all -k sample")

        self.assertFalse(result["ok"])
        self.assertIn(
            "Invalid test group id",
            result["error"],
        )
        run_allowed_command.assert_not_called()

    def test_test_tools_are_registered(self):
        self.assertIs(
            get_tool("test_list"),
            list_test_groups,
        )
        self.assertIs(
            get_tool("test_run"),
            run_test_group,
        )


if __name__ == "__main__":
    unittest.main()
