from __future__ import annotations

from pathlib import Path
from typing import Any

OUTER_WIDTH = 62
INNER_WIDTH = OUTER_WIDTH - 2


def _border() -> str:
    return "+" + ("-" * INNER_WIDTH) + "+"


def _title_border(title: str) -> str:
    title_text = f" {title} "
    remaining = INNER_WIDTH - len(title_text)
    left = remaining // 2
    right = remaining - left
    return "+" + ("-" * left) + title_text + ("-" * right) + "+"


def _line(text: str = "") -> str:
    safe_text = _ascii_only(str(text))
    if len(safe_text) > INNER_WIDTH:
        safe_text = safe_text[: INNER_WIDTH - 3] + "..."
    return "|" + safe_text.ljust(INNER_WIDTH) + "|"


def _field(label: str, value: Any) -> str:
    return _line(f" {label:<9}: {_ascii_only(str(value))}")


def _ascii_only(value: str) -> str:
    return "".join(ch if ord(ch) < 128 else "?" for ch in value)


def _short_log_path(log_path: Any) -> str:
    if log_path is None:
        return ""

    raw = str(log_path)
    if not raw:
        return ""

    name = Path(raw).name
    if name and ("logs" in raw.lower() or "sessions" in raw.lower()):
        return "logs\\sessions\\" + name
    return raw


def render_startup_screen(
    version: str | None = None,
    model: str | None = None,
    internet_status: str | None = None,
    status: str | None = None,
    log_path: Any | None = None,
) -> None:
    version = version or "v0.7.0"
    model = model or "vega-core"
    internet_status = internet_status or "OFF"
    status = status or "Ready"
    log_value = _short_log_path(log_path)

    lines = [
        _border(),
        _line(''),
        _line('       __      __  ______   _____      _'),
        _line('       \\ \\    / / |  ____| / ____|    / \\'),
        _line('        \\ \\  / /  | |__   | |  __    / _ \\'),
        _line('         \\ \\/ /   |  __|  | | |_ |  / ___ \\'),
        _line('          \\  /    | |____ | |__| | / /   \\ \\'),
        _line('           \\/     |______| \\_____|/_/     \\_\\'),
        _line(''),
        _line('              Local Project Coding-Agent'),
        _line(''),
        _border(),
        "",
        _title_border("VEGA SESSION"),
        _field("Version", version),
        _field("Model", model),
        _field("Internet", internet_status),
        _field("Status", status),
        _field("Log", log_value),
        _border(),
        "",
        "Commands: /workspace  |  /task  |  /docs  |  /status  |  /help  |  /exit",
    ]

    print("\n".join(lines))

