"""In-memory internet state for the current VEGA process."""

from __future__ import annotations

from threading import RLock


_LOCK = RLock()
_ENABLED = False


def is_internet_enabled() -> bool:
    """Return whether internet access is enabled for this process."""
    with _LOCK:
        return _ENABLED


def set_internet_enabled(enabled: bool) -> bool:
    """Set internet access for this process and return the new state."""
    if not isinstance(enabled, bool):
        raise TypeError("Internet state must be boolean.")

    global _ENABLED

    with _LOCK:
        _ENABLED = enabled
        return _ENABLED


def reset_internet_state() -> None:
    """Reset internet access to its safe default."""
    set_internet_enabled(False)
