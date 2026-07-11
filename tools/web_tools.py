"""Controlled read-only web access for VEGA."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from core.internet_state import is_internet_enabled
from core.network_safety import (
    NetworkSafetyError,
    load_internet_policy,
    sanitize_url_for_audit,
    validate_url,
)


def _result(
    data: Any = None,
    error: str | None = None,
) -> dict:
    return {
        "ok": error is None,
        "error": error,
        "data": data if error is None else None,
    }


def _project_root(
    project_root: Path | str | None,
) -> Path:
    root = (
        Path(project_root)
        if project_root is not None
        else Path(__file__).resolve().parents[1]
    )

    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise NetworkSafetyError(
            "Project root does not exist."
        ) from exc

    if not root.is_dir():
        raise NetworkSafetyError(
            "Project root is not a directory."
        )

    return root


def _write_audit(
    root: Path,
    record: dict[str, Any],
) -> str | None:
    try:
        audit_path = (
            root
            / "logs"
            / "web"
            / "web_requests.jsonl"
        )
        audit_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with audit_path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )

        return None
    except OSError as exc:
        return f"Web audit warning: {exc}"


def _content_type_allowed(
    content_type: str,
    allowed_types: tuple[str, ...],
) -> bool:
    normalized = content_type.lower().strip()

    for allowed in allowed_types:
        if allowed.endswith("/"):
            if normalized.startswith(allowed):
                return True
        elif normalized == allowed:
            return True

    return False


def fetch_url(
    url: str,
    project_root: Path | str | None = None,
) -> dict:
    """Fetch one bounded text resource without redirects."""
    root: Path | None = None
    audit_url = sanitize_url_for_audit(
        url if isinstance(url, str) else ""
    )

    try:
        root = _project_root(project_root)

        if not is_internet_enabled():
            raise NetworkSafetyError(
                "Internet access is disabled. "
                "Run /internet on first."
            )

        policy = load_internet_policy(root)
        target = validate_url(url, policy)

        session = requests.Session()
        session.trust_env = False

        response = None

        try:
            response = session.get(
                target["url"],
                headers={
                    "User-Agent": policy["user_agent"],
                    "Accept": (
                        "text/plain, text/html, "
                        "application/json, application/xml"
                    ),
                },
                timeout=policy[
                    "request_timeout_seconds"
                ],
                allow_redirects=False,
                stream=True,
            )

            if 300 <= response.status_code < 400:
                raise NetworkSafetyError(
                    "HTTP redirects are blocked."
                )

            if not 200 <= response.status_code < 300:
                raise NetworkSafetyError(
                    "Remote server returned HTTP "
                    f"{response.status_code}."
                )

            raw_content_type = response.headers.get(
                "Content-Type",
                "",
            )
            content_type = (
                raw_content_type
                .split(";", 1)[0]
                .strip()
                .lower()
            )

            if not content_type:
                raise NetworkSafetyError(
                    "Response Content-Type is missing."
                )

            if not _content_type_allowed(
                content_type,
                policy["allowed_content_types"],
            ):
                raise NetworkSafetyError(
                    "Response content type is blocked: "
                    f"{content_type}"
                )

            content_length = response.headers.get(
                "Content-Length"
            )

            if content_length:
                try:
                    declared_size = int(content_length)
                except ValueError as exc:
                    raise NetworkSafetyError(
                        "Response Content-Length is invalid."
                    ) from exc

                if (
                    declared_size
                    > policy["max_response_bytes"]
                ):
                    raise NetworkSafetyError(
                        "Response exceeds the configured "
                        "size limit."
                    )

            chunks: list[bytes] = []
            total = 0
            truncated = False
            maximum = policy["max_response_bytes"]

            for chunk in response.iter_content(
                chunk_size=8192,
            ):
                if not chunk:
                    continue

                remaining = maximum - total

                if len(chunk) > remaining:
                    chunks.append(chunk[:remaining])
                    total += remaining
                    truncated = True
                    break

                chunks.append(chunk)
                total += len(chunk)

            raw = b"".join(chunks)
            encoding = response.encoding or "utf-8"
            text = raw.decode(
                encoding,
                errors="replace",
            )

            warning = _write_audit(
                root,
                {
                    "timestamp": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "operation": "fetch",
                    "url": audit_url,
                    "hostname": target["hostname"],
                    "resolved_addresses": (
                        target["resolved_addresses"]
                    ),
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "bytes_read": total,
                    "truncated": truncated,
                    "ok": True,
                },
            )

            return _result(
                {
                    "url": audit_url,
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "bytes_read": total,
                    "truncated": truncated,
                    "text": text,
                    "warning": warning,
                }
            )

        finally:
            if response is not None:
                response.close()

            session.close()

    except (
        NetworkSafetyError,
        requests.RequestException,
        OSError,
    ) as exc:
        warning = None

        if root is not None:
            warning = _write_audit(
                root,
                {
                    "timestamp": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "operation": "fetch",
                    "url": audit_url,
                    "ok": False,
                    "error": str(exc),
                },
            )

        message = str(exc)

        if warning:
            message = f"{message} {warning}"

        return _result(error=message)
