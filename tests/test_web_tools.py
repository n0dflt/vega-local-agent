import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from core.internet_state import (
    reset_internet_state,
    set_internet_enabled,
)
from tools.web_tools import fetch_url


POLICY = {
    "schema_version": 1,
    "enabled_by_default": False,
    "allowed_schemes": ["https"],
    "allowed_ports": [443],
    "request_timeout_seconds": 10,
    "max_response_bytes": 200000,
    "max_url_length": 2048,
    "allowed_content_types": [
        "text/",
        "application/json",
        "application/xml",
        "application/xhtml+xml",
        "application/rss+xml",
        "application/atom+xml",
    ],
    "user_agent": "VEGA/1.9 Controlled Internet Layer",
}


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        headers=None,
        chunks=None,
        encoding="utf-8",
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self.chunks = chunks or []
        self.encoding = encoding
        self.closed = False

    def iter_content(self, chunk_size=8192):
        yield from self.chunks

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.trust_env = True
        self.closed = False
        self.request_kwargs = None

    def get(self, url, **kwargs):
        self.request_kwargs = {
            "url": url,
            **kwargs,
        }

        if self.error is not None:
            raise self.error

        return self.response

    def close(self):
        self.closed = True


class WebToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

        config_directory = self.root / "config"
        config_directory.mkdir(parents=True)

        policy_path = config_directory / "internet_policy.json"
        policy_path.write_text(
            json.dumps(POLICY),
            encoding="utf-8",
        )

        reset_internet_state()

    def tearDown(self):
        reset_internet_state()
        self.temporary.cleanup()

    def validated_target(self):
        return {
            "url": "https://example.com/page?token=secret",
            "scheme": "https",
            "hostname": "example.com",
            "port": 443,
            "resolved_addresses": ("93.184.216.34",),
        }

    def test_fetch_is_blocked_when_internet_is_disabled(self):
        with patch(
            "tools.web_tools.requests.Session"
        ) as session_class:
            result = fetch_url(
                "https://example.com",
                self.root,
            )

        self.assertFalse(result["ok"])
        self.assertIn(
            "Internet access is disabled",
            result["error"],
        )
        session_class.assert_not_called()

    def test_fetches_bounded_text_response(self):
        set_internet_enabled(True)

        response = FakeResponse(
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Content-Length": "11",
            },
            chunks=[b"hello world"],
        )
        session = FakeSession(response=response)

        with (
            patch(
                "tools.web_tools.requests.Session",
                return_value=session,
            ),
            patch(
                "tools.web_tools.validate_url",
                return_value=self.validated_target(),
            ),
        ):
            result = fetch_url(
                "https://example.com/page?token=secret",
                self.root,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["data"]["text"],
            "hello world",
        )
        self.assertEqual(
            result["data"]["bytes_read"],
            11,
        )
        self.assertFalse(
            result["data"]["truncated"]
        )
        self.assertFalse(session.trust_env)
        self.assertFalse(
            session.request_kwargs["allow_redirects"]
        )
        self.assertTrue(response.closed)
        self.assertTrue(session.closed)

        audit_path = (
            self.root
            / "logs"
            / "web"
            / "web_requests.jsonl"
        )

        self.assertTrue(audit_path.exists())

        audit_record = json.loads(
            audit_path.read_text(
                encoding="utf-8"
            ).splitlines()[0]
        )

        self.assertEqual(
            audit_record["url"],
            "https://example.com/page",
        )

    def test_rejects_redirect_response(self):
        set_internet_enabled(True)

        response = FakeResponse(
            status_code=302,
            headers={
                "Content-Type": "text/plain",
            },
        )
        session = FakeSession(response=response)

        with (
            patch(
                "tools.web_tools.requests.Session",
                return_value=session,
            ),
            patch(
                "tools.web_tools.validate_url",
                return_value=self.validated_target(),
            ),
        ):
            result = fetch_url(
                "https://example.com/page",
                self.root,
            )

        self.assertFalse(result["ok"])
        self.assertIn(
            "redirects are blocked",
            result["error"],
        )

    def test_rejects_binary_content_type(self):
        set_internet_enabled(True)

        response = FakeResponse(
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": "4",
            },
            chunks=[b"data"],
        )
        session = FakeSession(response=response)

        with (
            patch(
                "tools.web_tools.requests.Session",
                return_value=session,
            ),
            patch(
                "tools.web_tools.validate_url",
                return_value=self.validated_target(),
            ),
        ):
            result = fetch_url(
                "https://example.com/file",
                self.root,
            )

        self.assertFalse(result["ok"])
        self.assertIn(
            "content type is blocked",
            result["error"],
        )

    def test_rejects_declared_oversized_response(self):
        set_internet_enabled(True)

        response = FakeResponse(
            headers={
                "Content-Type": "text/plain",
                "Content-Length": "200001",
            },
        )
        session = FakeSession(response=response)

        with (
            patch(
                "tools.web_tools.requests.Session",
                return_value=session,
            ),
            patch(
                "tools.web_tools.validate_url",
                return_value=self.validated_target(),
            ),
        ):
            result = fetch_url(
                "https://example.com/large",
                self.root,
            )

        self.assertFalse(result["ok"])
        self.assertIn(
            "size limit",
            result["error"],
        )

    def test_truncates_stream_at_configured_limit(self):
        set_internet_enabled(True)

        response = FakeResponse(
            headers={
                "Content-Type": "text/plain",
            },
            chunks=[
                b"a" * 199999,
                b"bc",
            ],
        )
        session = FakeSession(response=response)

        with (
            patch(
                "tools.web_tools.requests.Session",
                return_value=session,
            ),
            patch(
                "tools.web_tools.validate_url",
                return_value=self.validated_target(),
            ),
        ):
            result = fetch_url(
                "https://example.com/large",
                self.root,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(
            result["data"]["truncated"]
        )
        self.assertEqual(
            result["data"]["bytes_read"],
            200000,
        )
        self.assertEqual(
            len(result["data"]["text"]),
            200000,
        )

    def test_returns_controlled_request_error(self):
        set_internet_enabled(True)

        session = FakeSession(
            error=requests.RequestException(
                "connection failed"
            )
        )

        with (
            patch(
                "tools.web_tools.requests.Session",
                return_value=session,
            ),
            patch(
                "tools.web_tools.validate_url",
                return_value=self.validated_target(),
            ),
        ):
            result = fetch_url(
                "https://example.com/page",
                self.root,
            )

        self.assertFalse(result["ok"])
        self.assertIn(
            "connection failed",
            result["error"],
        )
        self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()
