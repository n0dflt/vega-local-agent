import socket
import unittest

from core.network_safety import (
    NetworkSafetyError,
    load_internet_policy,
    sanitize_url_for_audit,
    validate_url,
)


def public_resolver(host, port, type=socket.SOCK_STREAM):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", port),
        )
    ]


def private_resolver(host, port, type=socket.SOCK_STREAM):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("192.168.1.10", port),
        )
    ]


class InternetPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_internet_policy()

    def test_policy_is_disabled_by_default(self):
        self.assertFalse(
            self.policy["enabled_by_default"]
        )

    def test_policy_allows_only_https(self):
        self.assertEqual(
            self.policy["allowed_schemes"],
            ("https",),
        )

    def test_policy_allows_only_port_443(self):
        self.assertEqual(
            self.policy["allowed_ports"],
            (443,),
        )


class NetworkSafetyTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_internet_policy()

    def test_accepts_public_https_url(self):
        result = validate_url(
            "https://example.com/documentation",
            self.policy,
            resolver=public_resolver,
        )

        self.assertEqual(
            result["hostname"],
            "example.com",
        )
        self.assertEqual(
            result["port"],
            443,
        )
        self.assertEqual(
            result["resolved_addresses"],
            ("93.184.216.34",),
        )

    def test_rejects_http_url(self):
        with self.assertRaisesRegex(
            NetworkSafetyError,
            "Only HTTPS",
        ):
            validate_url(
                "http://example.com",
                self.policy,
                resolver=public_resolver,
            )

    def test_rejects_localhost(self):
        with self.assertRaisesRegex(
            NetworkSafetyError,
            "Localhost",
        ):
            validate_url(
                "https://localhost",
                self.policy,
                resolver=public_resolver,
            )

    def test_rejects_private_direct_ip(self):
        with self.assertRaisesRegex(
            NetworkSafetyError,
            "non-public",
        ):
            validate_url(
                "https://192.168.1.10",
                self.policy,
            )

    def test_rejects_private_resolved_address(self):
        with self.assertRaisesRegex(
            NetworkSafetyError,
            "non-public",
        ):
            validate_url(
                "https://example.com",
                self.policy,
                resolver=private_resolver,
            )

    def test_rejects_credentials_in_url(self):
        with self.assertRaisesRegex(
            NetworkSafetyError,
            "Credentials",
        ):
            validate_url(
                "https://user:password@example.com",
                self.policy,
                resolver=public_resolver,
            )

    def test_rejects_non_standard_port(self):
        with self.assertRaisesRegex(
            NetworkSafetyError,
            "Non-standard",
        ):
            validate_url(
                "https://example.com:8443",
                self.policy,
                resolver=public_resolver,
            )

    def test_rejects_whitespace(self):
        with self.assertRaisesRegex(
            NetworkSafetyError,
            "whitespace",
        ):
            validate_url(
                "https://example.com/test page",
                self.policy,
                resolver=public_resolver,
            )

    def test_audit_url_removes_query_and_fragment(self):
        result = sanitize_url_for_audit(
            "https://example.com/page?token=secret#section"
        )

        self.assertEqual(
            result,
            "https://example.com/page",
        )


if __name__ == "__main__":
    unittest.main()
