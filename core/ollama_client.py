"""Bounded HTTP client for the local Ollama chat API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


DEFAULT_API_URL = "http://localhost:11434/api/chat"
DEFAULT_TIMEOUT_SECONDS = 120


def api_error_message() -> str:
    """Return a stable message for unavailable Ollama runtime."""
    return "\n".join(
        [
            "Ollama API is unavailable.",
            "Check that Ollama is running.",
            "Then try:",
            "ollama list",
        ]
    )


def missing_model_message(model: str) -> str:
    """Return installation guidance for a missing model."""
    return (
        f"Model may not be installed. "
        f"Run: ollama pull {model}"
    )


def call_ollama_chat(
    model: str,
    messages: list[dict[str, str]],
    *,
    api_url: str = DEFAULT_API_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Send one non-streaming chat request to Ollama."""
    if not isinstance(model, str) or not model.strip():
        raise ValueError(
            "Ollama model name must not be empty."
        )

    if not isinstance(messages, list):
        raise TypeError(
            "Ollama messages must be a list."
        )

    payload = json.dumps(
        {
            "model": model.strip(),
            "messages": messages,
            "stream": False,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        if (
            exc.code == 404
            or "not found" in body.lower()
            or "model" in body.lower()
        ):
            return (
                False,
                (
                    f"Model `{model}` was not found.\n"
                    f"{missing_model_message(model)}"
                ),
            )

        return (
            False,
            body.strip()
            or (
                "Ollama API returned "
                f"HTTP {exc.code}."
            ),
        )
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ):
        return False, api_error_message()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return (
            False,
            raw.strip()
            or (
                "Ollama API returned an "
                "unreadable response."
            ),
        )

    if data.get("error"):
        error = str(data["error"])

        if (
            "not found" in error.lower()
            or "model" in error.lower()
        ):
            return (
                False,
                (
                    f"Model `{model}` was not found.\n"
                    f"{missing_model_message(model)}"
                ),
            )

        return False, error

    message = data.get("message", {})

    content = (
        message.get("content", "")
        if isinstance(message, dict)
        else ""
    )

    return True, content.strip()


def check_ollama_ready(
    model: str,
    *,
    api_url: str = DEFAULT_API_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Run a minimal Ollama chat health check."""
    messages = [
        {
            "role": "system",
            "content": "Reply with exactly: OK",
        },
        {
            "role": "user",
            "content": "health check",
        },
    ]

    return call_ollama_chat(
        model,
        messages,
        api_url=api_url,
        timeout=timeout,
    )
