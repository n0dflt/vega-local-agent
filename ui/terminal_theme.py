"""Small dependency-free terminal capability and symbol helpers."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True, slots=True)
class TerminalCapabilities:
    interactive: bool
    ansi: bool
    unicode: bool


def _supports_unicode(stream: TextIO) -> bool:
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        "╭─›⠋✓✗◆–█░…".encode(encoding)
    except (LookupError, UnicodeError):
        return False
    return True


def detect_terminal_capabilities(
    stream: TextIO | None = None,
    *,
    interactive: bool | None = None,
    ansi: bool | None = None,
    unicode: bool | None = None,
) -> TerminalCapabilities:
    stream = stream or sys.stdout
    if interactive is None:
        try:
            interactive = bool(stream.isatty())
        except Exception:
            interactive = False
    if unicode is None:
        unicode = _supports_unicode(stream)
    if ansi is None:
        disabled = "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb"
        windows_ansi = (
            os.name != "nt"
            or bool(os.environ.get("WT_SESSION"))
            or bool(os.environ.get("ANSICON"))
            or os.environ.get("ConEmuANSI") == "ON"
            or bool(os.environ.get("TERM_PROGRAM"))
        )
        ansi = bool(interactive and not disabled and windows_ansi)
    return TerminalCapabilities(bool(interactive), bool(ansi), bool(unicode))


__all__ = ["TerminalCapabilities", "detect_terminal_capabilities"]
