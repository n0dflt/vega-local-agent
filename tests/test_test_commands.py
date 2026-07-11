import unittest
from unittest.mock import patch

from core.command_handler import handle_test_command


class TestCommandHandlerTests(unittest.TestCase):
    @patch("tools.test_tools.list_test_groups")
    def test_test_list(self, list_test_groups):
        list_test_groups.return_value = {
            "ok": True,
            "error": None,
            "data": [
                {
                    "id": "all",
                    "description": "Run all VEGA tests.",
                    "command_id": "tests",
                    "available": True,
                    "enabled": True,
                },
                {
                    "id": "terminal",
                    "description": "Run all Terminal Tools tests.",
                    "command_id": "tests-terminal",
                    "available": False,
                    "enabled": False,
                },
            ],
        }

        output = handle_test_command("/test list")

        self.assertIn("Available test groups:", output)
        self.assertIn("all", output)
        self.assertIn("enabled", output)
        self.assertIn("terminal", output)
        self.assertIn("unavailable", output)

    @patch("tools.test_tools.run_test_group")
    def test_test_without_group_runs_all(
        self,
        run_test_group,
    ):
        run_test_group.return_value = {
            "ok": True,
            "error": None,
            "data": {
                "group_id": "all",
                "description": "Run all VEGA tests.",
                "command_id": "tests",
                "stdout": "27 passed\n",
                "stderr": "",
                "returncode": 0,
                "timed_out": False,
                "truncated": False,
                "duration_ms": 1200,
                "warning": None,
            },
        }

        output = handle_test_command("/test")

        run_test_group.assert_called_once_with("all", None)
        self.assertIn("Test group: all", output)
        self.assertIn("Status: PASS", output)
        self.assertIn("27 passed", output)

    @patch("tools.test_tools.run_test_group")
    def test_named_group_is_forwarded(
        self,
        run_test_group,
    ):
        run_test_group.return_value = {
            "ok": True,
            "error": None,
            "data": {
                "group_id": "terminal",
                "description": "Run all Terminal Tools tests.",
                "command_id": "tests-terminal",
                "stdout": "18 passed\n",
                "stderr": "",
                "returncode": 0,
                "timed_out": False,
                "truncated": False,
                "duration_ms": 800,
                "warning": None,
            },
        }

        output = handle_test_command("/test terminal")

        run_test_group.assert_called_once_with(
            "terminal",
            None,
        )
        self.assertIn("Test group: terminal", output)
        self.assertIn("Status: PASS", output)

    @patch("tools.test_tools.run_test_group")
    def test_failed_group_is_formatted(
        self,
        run_test_group,
    ):
        run_test_group.return_value = {
            "ok": False,
            "error": None,
            "data": {
                "group_id": "all",
                "description": "Run all VEGA tests.",
                "command_id": "tests",
                "stdout": "1 failed\n",
                "stderr": "failure details\n",
                "returncode": 1,
                "timed_out": False,
                "truncated": False,
                "duration_ms": 900,
                "warning": None,
            },
        }

        output = handle_test_command("/test all")

        self.assertIn("Status: FAIL", output)
        self.assertIn("Exit code: 1", output)
        self.assertIn("1 failed", output)
        self.assertIn("Errors:", output)
        self.assertIn("failure details", output)

    @patch("tools.test_tools.run_test_group")
    def test_unknown_group_error_is_formatted(
        self,
        run_test_group,
    ):
        run_test_group.return_value = {
            "ok": False,
            "error": "Unknown test group: unknown.",
            "data": None,
        }

        output = handle_test_command("/test unknown")

        self.assertIn(
            "Unknown test group: unknown",
            output,
        )
        self.assertIn("/test list", output)

    @patch("tools.test_tools.run_test_group")
    def test_extra_arguments_are_rejected(
        self,
        run_test_group,
    ):
        output = handle_test_command(
            "/test terminal -k sample"
        )

        self.assertIn(
            "Exactly one test group is allowed",
            output,
        )
        run_test_group.assert_not_called()


if __name__ == "__main__":
    unittest.main()
