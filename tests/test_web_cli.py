import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from core.internet_state import (
    reset_internet_state,
    set_internet_enabled,
)
from scripts.vega import (
    handle_command,
    help_text,
    internet_label,
    print_available_commands,
)


class WebCliRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.log_file = self.root / "session.log"
        self.model = "vega-core"
        reset_internet_state()

    def tearDown(self):
        reset_internet_state()
        self.temporary.cleanup()

    @patch("core.command_handler.handle_internet_command")
    def test_internet_status_is_routed(
        self,
        handle_internet_command,
    ):
        handle_internet_command.return_value = (
            "Internet access: OFF."
        )

        output = io.StringIO()

        with redirect_stdout(output):
            keep_running = handle_command(
                "/internet status",
                self.root,
                self.log_file,
                self.model,
            )

        self.assertTrue(keep_running)
        handle_internet_command.assert_called_once_with(
            "/internet status"
        )
        self.assertIn(
            "Internet access: OFF.",
            output.getvalue(),
        )

    @patch("core.command_handler.handle_internet_command")
    def test_internet_on_is_routed(
        self,
        handle_internet_command,
    ):
        handle_internet_command.return_value = (
            "Internet access enabled."
        )

        output = io.StringIO()

        with redirect_stdout(output):
            keep_running = handle_command(
                "/internet on",
                self.root,
                self.log_file,
                self.model,
            )

        self.assertTrue(keep_running)
        handle_internet_command.assert_called_once_with(
            "/internet on"
        )

    @patch("core.command_handler.handle_web_command")
    def test_web_fetch_is_routed(
        self,
        handle_web_command,
    ):
        handle_web_command.return_value = (
            "Status: 200\n\nhello"
        )

        output = io.StringIO()

        with redirect_stdout(output):
            keep_running = handle_command(
                "/web fetch https://example.com",
                self.root,
                self.log_file,
                self.model,
            )

        self.assertTrue(keep_running)
        handle_web_command.assert_called_once_with(
            "/web fetch https://example.com",
            self.root,
        )
        self.assertIn(
            "Status: 200",
            output.getvalue(),
        )

    def test_help_contains_internet_commands(self):
        output = help_text()

        self.assertIn("/internet", output)
        self.assertIn("/internet on", output)
        self.assertIn("/internet off", output)
        self.assertIn("/web fetch <https-url>", output)

    def test_available_commands_contains_web_layer(self):
        output = io.StringIO()

        with redirect_stdout(output):
            print_available_commands()

        commands = output.getvalue().splitlines()

        self.assertIn("/internet", commands)
        self.assertIn("/web", commands)

    def test_internet_label_follows_runtime_state(self):
        self.assertEqual(
            internet_label(),
            "OFF",
        )

        set_internet_enabled(True)

        self.assertEqual(
            internet_label(),
            "ON",
        )


if __name__ == "__main__":
    unittest.main()
