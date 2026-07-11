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


class DocumentationCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.log_file = self.root / "session.log"
        self.model = "vega-core"

    def tearDown(self):
        self.temporary.cleanup()

    @patch("core.command_handler.handle_docgen_command")
    def test_docgen_status_is_routed(
        self,
        handle_docgen_command,
    ):
        handle_docgen_command.return_value = (
            "Documentation Builder status"
        )

        output = io.StringIO()

        with redirect_stdout(output):
            keep_running = handle_command(
                "/docgen status",
                self.root,
                self.log_file,
                self.model,
            )

        self.assertTrue(keep_running)
        handle_docgen_command.assert_called_once_with(
            "/docgen status",
            self.root,
        )
        self.assertIn(
            "Documentation Builder status",
            output.getvalue(),
        )

    @patch("core.command_handler.handle_docgen_command")
    def test_docgen_check_is_routed(
        self,
        handle_docgen_command,
    ):
        handle_docgen_command.return_value = (
            "Documentation check\nStatus: PASS"
        )

        output = io.StringIO()

        with redirect_stdout(output):
            keep_running = handle_command(
                "/docgen check",
                self.root,
                self.log_file,
                self.model,
            )

        self.assertTrue(keep_running)
        handle_docgen_command.assert_called_once_with(
            "/docgen check",
            self.root,
        )
        self.assertIn(
            "Status: PASS",
            output.getvalue(),
        )

    def test_help_contains_docgen_commands(self):
        output = help_text()

        self.assertIn("/docgen", output)
        self.assertIn("/docgen status", output)
        self.assertIn("/docgen check", output)

    def test_available_commands_contains_docgen(self):
        output = io.StringIO()

        with redirect_stdout(output):
            print_available_commands()

        commands = output.getvalue().splitlines()

        self.assertIn("/docgen", commands)


if __name__ == "__main__":
    unittest.main()
