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
                {"id": "tests-web", "enabled": True},
                {"id": "tests-web-tools", "enabled": True},
                {"id": "tests-web-commands", "enabled": True},
                {"id": "tests-web-cli", "enabled": True},
                {"id": "tests-docs", "enabled": True},
                {"id": "tests-workflow", "enabled": True},
            ],
        }

        result = list_test_groups()

        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(len(result["data"]), 10)
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
        self.assertEqual(result["reason_code"], "")
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
    def test_skipped_tests_remain_successful(self, run_allowed_command):
        run_allowed_command.return_value = {
            "ok": True,
            "error": None,
            "data": {
                "command_id": "tests",
                "stdout": "10 passed, 2 skipped\n",
                "stderr": "",
                "returncode": 0,
                "timed_out": False,
                "truncated": False,
                "duration_ms": 100,
                "warning": None,
            },
        }

        result = run_test_group("all")

        self.assertTrue(result["ok"])
        self.assertEqual(result["reason_code"], "")
        self.assertIn("skipped", result["data"]["stdout"])

    @patch("tools.test_tools.run_allowed_command")
    def test_documentation_group_uses_allowed_command(
        self,
        run_allowed_command,
    ):
        run_allowed_command.return_value = {
            "ok": True,
            "error": None,
            "data": {
                "command_id": "tests-docs",
                "stdout": "24 passed\n",
                "stderr": "",
                "returncode": 0,
                "timed_out": False,
                "truncated": False,
                "duration_ms": 100,
                "warning": None,
            },
        }

        result = run_test_group("docs")

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["data"]["group_id"],
            "docs",
        )
        self.assertEqual(
            result["data"]["command_id"],
            "tests-docs",
        )
        run_allowed_command.assert_called_once_with(
            "tests-docs",
            None,
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
        self.assertEqual(result["reason_code"], "test_failure")
        self.assertEqual(
            result["data"]["returncode"],
            1,
        )
        self.assertIn(
            "1 failed",
            result["data"]["stdout"],
        )

    @patch("tools.test_tools.run_allowed_command")
    def test_all_nonzero_pytest_exit_codes_are_test_failures(
        self,
        run_allowed_command,
    ):
        for returncode in (1, 2, 5):
            with self.subTest(returncode=returncode):
                run_allowed_command.return_value = {
                    "ok": False,
                    "error": None,
                    "data": {
                        "command_id": "tests",
                        "stdout": "pytest did not pass\n",
                        "stderr": "",
                        "returncode": returncode,
                        "timed_out": False,
                        "truncated": False,
                        "duration_ms": 100,
                        "warning": None,
                    },
                }

                result = run_test_group("all")

                self.assertFalse(result["ok"])
                self.assertEqual(result["reason_code"], "test_failure")
                self.assertEqual(result["data"]["returncode"], returncode)

    @patch("tools.test_tools.run_allowed_command")
    def test_timeout_has_specific_reason(self, run_allowed_command):
        run_allowed_command.return_value = {
            "ok": False,
            "error": None,
            "reason_code": "timeout",
            "data": {
                "command_id": "tests",
                "stdout": "",
                "stderr": "timed out",
                "returncode": -1,
                "timed_out": True,
                "truncated": False,
                "duration_ms": 180000,
                "warning": None,
            },
        }

        result = run_test_group("all")

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "timeout")
        self.assertTrue(result["data"]["timed_out"])

    @patch("tools.test_tools.run_allowed_command")
    def test_runtime_unavailable_has_specific_reason(self, run_allowed_command):
        diagnostics = {
            "tool": "terminal_run",
            "resolved_executable": "python-runtime",
        }
        run_allowed_command.return_value = {
            "ok": False,
            "error": "Terminal command could not be started.",
            "data": None,
            "reason_code": "runtime_unavailable",
            "diagnostics": diagnostics,
        }

        result = run_test_group("all")

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "runtime_unavailable")
        self.assertIn("Python runtime", result["error"])

    @patch("tools.test_tools.run_allowed_command")
    def test_malformed_result_has_parse_reason(self, run_allowed_command):
        run_allowed_command.return_value = {
            "ok": True,
            "error": None,
            "data": {
                "returncode": "0",
                "timed_out": False,
            },
        }

        result = run_test_group("all")

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "result_parse_error")
        self.assertIn("could not be parsed", result["error"])

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
