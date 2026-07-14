"""Compact VEGA input prompt with a conservative ASCII fallback."""

from __future__ import annotations

import re
import sys
from typing import TextIO

from ui.terminal_theme import detect_terminal_capabilities


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _label(value: object, fallback: str) -> str:
    text = _CONTROL.sub("", str(value)).strip()
    return text[:80] or fallback


def render_terminal_prompt(
    model: object,
    environment: object = "LOCAL",
    *,
    stream: TextIO | None = None,
    unicode: bool | None = None,
    color: bool = False,
) -> str:
    """Render a real-state prompt; color is opt-in and never required."""

    stream = stream or sys.stdout
    capabilities = detect_terminal_capabilities(stream, unicode=unicode)
    model_label = _label(model, "unknown-model")
    environment_label = _label(environment, "LOCAL")
    if capabilities.unicode:
        first = f"╭─ VEGA ─ {model_label} ─ {environment_label}"
        second = "╰─› Напишите задачу… "
    else:
        first = f"VEGA [{model_label}] [{environment_label}]"
        second = "> Enter task... "
    if color and capabilities.ansi:
        return f"\x1b[36m{first}\x1b[0m\n{second}"
    return f"{first}\n{second}"


__all__ = ["render_terminal_prompt"]
