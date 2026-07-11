import unittest
from unittest.mock import patch

from core.command_handler import (
    INTERNET_HELP,
    WEB_HELP,
    handle_internet_command,
    handle_web_command,
)
from core.internet_state import reset_internet_state
from tools.registry import get_tool


class InternetCommandTests(unittest.TestCase):
    def setUp(self):
        reset_internet_state()

    def tearDown(self):
        reset_internet_state()

    def test_status_is_off_by_default(self):
        result = handle_internet_command(
            "/internet status"
        )

        self.assertEqual(
            result,
            "Internet access: OFF.",
        )

    def test_internet_can_be_enabled(self):
        result = handle_internet_command(
            "/internet on"
        )

        self.assertIn(
            "enabled",
            result,
        )

        self.assertEqual(
            handle_internet_command("/internet"),
            "Internet access: ON.",
        )

    def test_internet_can_be_disabled(self):
        handle_internet_command("/internet on")

        result = handle_internet_command(
            "/internet off"
        )

        self.assertIn(
            "disabled",
            result,
        )

        self.assertEqual(
            handle_internet_command("/internet"),
            "Internet access: OFF.",
        )

    def test_unknown_internet_action_returns_help(self):
        result = handle_internet_command(
            "/internet invalid"
        )

        self.assertEqual(
            result,
            INTERNET_HELP,
        )


class WebCommandTests(unittest.TestCase):
    def test_web_without_fetch_returns_help(self):
        result = handle_web_command("/web")

        self.assertEqual(
            result,
            WEB_HELP,
        )

    @patch("tools.web_tools.fetch_url")
    def test_successful_fetch_is_rendered(
        self,
        fetch_url,
    ):
        fetch_url.return_value = {
            "ok": True,
            "error": None,
            "data": {
                "url": "https://example.com/page",
                "status_code": 200,
                "content_type": "text/plain",
                "bytes_read": 5,
                "truncated": False,
                "text": "hello",
                "warning": None,
            },
        }

        result = handle_web_command(
            "/web fetch https://example.com/page",
            ".",
        )

        fetch_url.assert_called_once_with(
            "https://example.com/page",
            ".",
        )

        self.assertIn(
            "Status: 200",
            result,
        )
        self.assertIn(
            "hello",
            result,
        )

    @patch("tools.web_tools.fetch_url")
    def test_fetch_error_is_controlled(
        self,
        fetch_url,
    ):
        fetch_url.return_value = {
            "ok": False,
            "error": "Internet access is disabled.",
            "data": None,
        }

        result = handle_web_command(
            "/web fetch https://example.com",
            ".",
        )

        self.assertEqual(
            result,
            (
                "Web command error: "
                "Internet access is disabled."
            ),
        )

    def test_registry_contains_internet_and_web_tools(self):
        self.assertIsNotNone(
            get_tool("internet_status")
        )
        self.assertIsNotNone(
            get_tool("internet_set")
        )
        self.assertIsNotNone(
            get_tool("web_fetch")
        )


if __name__ == "__main__":
    unittest.main()
