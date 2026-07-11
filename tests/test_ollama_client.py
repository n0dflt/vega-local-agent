import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from core.ollama_client import (
    api_error_message,
    call_ollama_chat,
    check_ollama_ready,
)


class OllamaClientTests(unittest.TestCase):
    @patch(
        "core.ollama_client."
        "urllib.request.urlopen"
    )
    def test_successful_chat_response(
        self,
        urlopen,
    ) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"message":{"content":"  Hello  "}}'
        )
        urlopen.return_value = response

        ok, content = call_ollama_chat(
            "test-model",
            [
                {
                    "role": "user",
                    "content": "Hello",
                }
            ],
        )

        self.assertTrue(ok)
        self.assertEqual(
            content,
            "Hello",
        )

    @patch(
        "core.ollama_client."
        "urllib.request.urlopen"
    )
    def test_request_contains_model_and_messages(
        self,
        urlopen,
    ) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"message":{"content":"OK"}}'
        )
        urlopen.return_value = response

        messages = [
            {
                "role": "user",
                "content": "Test",
            }
        ]

        call_ollama_chat(
            "test-model",
            messages,
        )

        request = urlopen.call_args.args[0]
        payload = json.loads(
            request.data.decode("utf-8")
        )

        self.assertEqual(
            payload["model"],
            "test-model",
        )
        self.assertEqual(
            payload["messages"],
            messages,
        )
        self.assertFalse(
            payload["stream"]
        )

    @patch(
        "core.ollama_client."
        "urllib.request.urlopen"
    )
    def test_unavailable_api_returns_stable_error(
        self,
        urlopen,
    ) -> None:
        urlopen.side_effect = (
            urllib.error.URLError(
                "connection refused"
            )
        )

        ok, content = call_ollama_chat(
            "test-model",
            [],
        )

        self.assertFalse(ok)
        self.assertEqual(
            content,
            api_error_message(),
        )

    @patch(
        "core.ollama_client."
        "urllib.request.urlopen"
    )
    def test_invalid_json_is_rejected(
        self,
        urlopen,
    ) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = (
            b"invalid-response"
        )
        urlopen.return_value = response

        ok, content = call_ollama_chat(
            "test-model",
            [],
        )

        self.assertFalse(ok)
        self.assertEqual(
            content,
            "invalid-response",
        )

    @patch(
        "core.ollama_client."
        "urllib.request.urlopen"
    )
    def test_model_error_contains_install_command(
        self,
        urlopen,
    ) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"error":"model not found"}'
        )
        urlopen.return_value = response

        ok, content = call_ollama_chat(
            "missing-model",
            [],
        )

        self.assertFalse(ok)
        self.assertIn(
            "ollama pull missing-model",
            content,
        )

    @patch(
        "core.ollama_client.call_ollama_chat"
    )
    def test_health_check_uses_chat_client(
        self,
        call_chat,
    ) -> None:
        call_chat.return_value = (
            True,
            "OK",
        )

        result = check_ollama_ready(
            "test-model"
        )

        self.assertEqual(
            result,
            (True, "OK"),
        )
        call_chat.assert_called_once()


if __name__ == "__main__":
    unittest.main()
