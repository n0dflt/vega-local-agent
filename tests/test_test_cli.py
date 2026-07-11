import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.vega import (
    handle_command,
    help_text,
    print_available_commands,
)


class TestCliRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.log_file = self.root / "session.log"
        self.model = "vega-core"

    def tearDown(self):
        self.temporary.cleanup()

    @patch("core.command_handler.handle_test_command")
    def test_test_command_is_routed(
        self,
        handle_test_command,
    ):
        handle_test_command.return_value = "Test group: all"

        output = io.StringIO()

        with redirect_stdout(output):
            keep_running = handle_command(
                "/test",
                self.root,
                self.log_file,
                self.model,
            )

        self.assertTrue(keep_running)
        handle_test_command.assert_called_once_with(
            "/test",
            self.root,
        )
        self.assertIn(
            "Test group: all",
            output.getvalue(),
        )

    @patch("core.command_handler.handle_test_command")
    def test_named_test_group_is_routed(
        self,
        handle_test_command,
    ):
        handle_test_command.return_value = (
            "Test group: terminal"
        )

        output = io.StringIO()

        with redirect_stdout(output):
            keep_running = handle_command(
                "/test terminal",
                self.root,
                self.log_file,
                self.model,
            )

        self.assertTrue(keep_running)
        handle_test_command.assert_called_once_with(
            "/test terminal",
            self.root,
        )
        self.assertIn(
            "Test group: terminal",
            output.getvalue(),
        )

    def test_help_contains_test_runner(self):
        output = help_text()

        self.assertIn(
            "/test",
            output,
        )
        self.assertIn(
            "/test list",
            output,
        )
        self.assertIn(
            "/test <group-id>",
            output,
        )

    def test_available_commands_contains_test(self):
        output = io.StringIO()

        with redirect_stdout(output):
            print_available_commands()

        self.assertIn(
            "/test",
            output.getvalue().splitlines(),
        )


if __name__ == "__main__":
    unittest.main()
