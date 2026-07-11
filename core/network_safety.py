"""Network policy and SSRF protection for VEGA web tools."""

from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit


SUPPORTED_SCHEMA_VERSION = 1
HARD_ALLOWED_SCHEMES = frozenset({"https"})
HARD_ALLOWED_PORTS = frozenset({443})
MAX_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 1_000_000
MAX_URL_LENGTH = 4096


class NetworkSafetyError(ValueError):
    """Controlled, user-facing network safety error."""


def _project_root(project_root: Path | str | None = None) -> Path:
    root = (
        Path(project_root)
        if project_root is not None
        else Path(__file__).resolve().parents[1]
    )

    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise NetworkSafetyError("Project root does not exist.") from exc

    if not root.is_dir():
        raise NetworkSafetyError("Project root is not a directory.")

    return root


def _positive_integer(
    value: Any,
    field: str,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
    ):
        raise NetworkSafetyError(
            f"{field} must be a positive integer."
        )

    if value > maximum:
        raise NetworkSafetyError(
            f"{field} must not exceed {maximum}."
        )

    return value


def load_internet_policy(
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Load and strictly validate config/internet_policy.json."""
    root = _project_root(project_root)
    policy_path = root / "config" / "internet_policy.json"

    try:
        resolved_policy = policy_path.resolve(strict=True)
    except OSError as exc:
        raise NetworkSafetyError(
            "Internet policy file was not found."
        ) from exc

    try:
        resolved_policy.relative_to(root)
    except ValueError as exc:
        raise NetworkSafetyError(
            "Internet policy must be inside the project root."
        ) from exc

    if not resolved_policy.is_file():
        raise NetworkSafetyError(
            "Internet policy path is not a file."
        )

    try:
        policy = json.loads(
            resolved_policy.read_text(encoding="utf-8-sig")
        )
    except json.JSONDecodeError as exc:
        raise NetworkSafetyError(
            "Internet policy JSON is invalid."
        ) from exc
    except OSError as exc:
        raise NetworkSafetyError(
            "Internet policy could not be read."
        ) from exc

    if not isinstance(policy, dict):
        raise NetworkSafetyError(
            "Internet policy root must be an object."
        )

    if policy.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise NetworkSafetyError(
            "Internet policy schema_version is not supported."
        )

    if policy.get("enabled_by_default") is not False:
        raise NetworkSafetyError(
            "Internet must be disabled by default."
        )

    schemes = policy.get("allowed_schemes")

    if (
        not isinstance(schemes, list)
        or not schemes
        or not all(isinstance(item, str) for item in schemes)
    ):
        raise NetworkSafetyError(
            "allowed_schemes must be a non-empty string list."
        )

    normalized_schemes = {
        item.strip().lower()
        for item in schemes
    }

    if not normalized_schemes.issubset(HARD_ALLOWED_SCHEMES):
        raise NetworkSafetyError(
            "Only HTTPS is allowed."
        )

    ports = policy.get("allowed_ports")

    if (
        not isinstance(ports, list)
        or not ports
        or not all(
            isinstance(item, int)
            and not isinstance(item, bool)
            for item in ports
        )
    ):
        raise NetworkSafetyError(
            "allowed_ports must be a non-empty integer list."
        )

    normalized_ports = set(ports)

    if not normalized_ports.issubset(HARD_ALLOWED_PORTS):
        raise NetworkSafetyError(
            "Only the standard HTTPS port is allowed."
        )

    timeout = _positive_integer(
        policy.get("request_timeout_seconds"),
        "request_timeout_seconds",
        MAX_TIMEOUT_SECONDS,
    )

    max_response_bytes = _positive_integer(
        policy.get("max_response_bytes"),
        "max_response_bytes",
        MAX_RESPONSE_BYTES,
    )

    max_url_length = _positive_integer(
        policy.get("max_url_length"),
        "max_url_length",
        MAX_URL_LENGTH,
    )

    content_types = policy.get("allowed_content_types")

    if (
        not isinstance(content_types, list)
        or not content_types
        or not all(
            isinstance(item, str) and item.strip()
            for item in content_types
        )
    ):
        raise NetworkSafetyError(
            "allowed_content_types must be a non-empty string list."
        )

    user_agent = policy.get("user_agent")

    if not isinstance(user_agent, str) or not user_agent.strip():
        raise NetworkSafetyError(
            "user_agent must be a non-empty string."
        )

    return {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "enabled_by_default": False,
        "allowed_schemes": tuple(sorted(normalized_schemes)),
        "allowed_ports": tuple(sorted(normalized_ports)),
        "request_timeout_seconds": timeout,
        "max_response_bytes": max_response_bytes,
        "max_url_length": max_url_length,
        "allowed_content_types": tuple(
            item.strip().lower()
            for item in content_types
        ),
        "user_agent": user_agent.strip(),
    }


def _validate_ip_address(address: str) -> str:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise NetworkSafetyError(
            f"Resolved address is invalid: {address}"
        ) from exc

    if not parsed.is_global:
        raise NetworkSafetyError(
            "Local, private, reserved, or non-public "
            "network addresses are blocked."
        )

    return str(parsed)


def validate_url(
    url: str,
    policy: dict[str, Any],
    resolver: Callable[..., list] = socket.getaddrinfo,
) -> dict[str, Any]:
    """Validate an HTTPS URL and resolve it to public IP addresses."""
    if not isinstance(url, str) or not url.strip():
        raise NetworkSafetyError(
            "URL must be a non-empty string."
        )

    normalized_url = url.strip()

    if len(normalized_url) > policy["max_url_length"]:
        raise NetworkSafetyError(
            "URL exceeds the configured length limit."
        )

    if any(character.isspace() for character in normalized_url):
        raise NetworkSafetyError(
            "URL must not contain whitespace."
        )

    try:
        parsed = urlsplit(normalized_url)
    except ValueError as exc:
        raise NetworkSafetyError("URL is invalid.") from exc

    scheme = parsed.scheme.lower()

    if scheme not in policy["allowed_schemes"]:
        raise NetworkSafetyError(
            "Only HTTPS URLs are allowed."
        )

    if not parsed.hostname:
        raise NetworkSafetyError(
            "URL hostname is required."
        )

    if parsed.username is not None or parsed.password is not None:
        raise NetworkSafetyError(
            "Credentials inside URLs are blocked."
        )

    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise NetworkSafetyError(
            "URL port is invalid."
        ) from exc

    if port not in policy["allowed_ports"]:
        raise NetworkSafetyError(
            "Non-standard network ports are blocked."
        )

    raw_hostname = parsed.hostname.rstrip(".").lower()

    if (
        raw_hostname == "localhost"
        or raw_hostname.endswith(".localhost")
        or "%" in raw_hostname
    ):
        raise NetworkSafetyError(
            "Localhost addresses are blocked."
        )

    resolved_addresses: set[str] = set()

    try:
        direct_ip = ipaddress.ip_address(raw_hostname)
    except ValueError:
        try:
            hostname = raw_hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise NetworkSafetyError(
                "URL hostname is invalid."
            ) from exc

        try:
            records = resolver(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise NetworkSafetyError(
                "Hostname could not be resolved."
            ) from exc

        for record in records:
            address = record[4][0]
            resolved_addresses.add(
                _validate_ip_address(address)
            )
    else:
        hostname = raw_hostname
        resolved_addresses.add(
            _validate_ip_address(str(direct_ip))
        )

    if not resolved_addresses:
        raise NetworkSafetyError(
            "Hostname did not resolve to an address."
        )

    return {
        "url": normalized_url,
        "scheme": scheme,
        "hostname": hostname,
        "port": port,
        "resolved_addresses": tuple(
            sorted(resolved_addresses)
        ),
    }


def sanitize_url_for_audit(url: str) -> str:
    """Remove query parameters and fragments before audit logging."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "[invalid URL]"

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",
            "",
        )
    )
