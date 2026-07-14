"""Request-local, payload-free execution progress events."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


MAX_PROGRESS_TITLE_CHARS = 120
_ENDPOINT_WORD = re.compile(r"\bendpoint\b", re.IGNORECASE)


class ExecutionProgressError(ValueError):
    """Raised when a public progress event is structurally invalid."""


class ExecutionProgressStage(str, Enum):
    RECEIVED = "received"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    STEP_RUNNING = "step_running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    STEP_COMPLETED = "step_completed"
    STEP_SKIPPED = "step_skipped"
    STEP_FAILED = "step_failed"
    COMPLETED = "completed"
    FAILED = "failed"


def safe_progress_title(value: object) -> str:
    """Return one bounded terminal-safe label without execution payload data."""

    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.split())
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) not in {"Cc", "Cf"}
    )
    normalized = _ENDPOINT_WORD.sub("operation", normalized).strip()
    return normalized[:MAX_PROGRESS_TITLE_CHARS].rstrip()


@dataclass(frozen=True, slots=True)
class ExecutionProgressEvent:
    """Immutable public state for one execution-local UI update."""

    stage: ExecutionProgressStage
    current_step: int = 0
    total_steps: int = 0
    title: str = ""
    plan_titles: tuple[str, ...] = ()
    elapsed_seconds: float | None = None

    def __post_init__(self) -> None:
        try:
            stage = (
                self.stage
                if isinstance(self.stage, ExecutionProgressStage)
                else ExecutionProgressStage(str(self.stage))
            )
        except ValueError as exc:
            raise ExecutionProgressError("unknown progress stage") from exc
        if type(self.current_step) is not int or self.current_step < 0:
            raise ExecutionProgressError("current_step must be a non-negative integer")
        if type(self.total_steps) is not int or self.total_steps < 0:
            raise ExecutionProgressError("total_steps must be a non-negative integer")
        if self.current_step > self.total_steps:
            raise ExecutionProgressError("current_step must not exceed total_steps")

        titles = tuple(safe_progress_title(value) for value in self.plan_titles)
        if any(not value for value in titles):
            raise ExecutionProgressError("plan titles must not be empty")
        if stage is ExecutionProgressStage.PLAN_READY and len(titles) != self.total_steps:
            raise ExecutionProgressError("PLAN_READY total_steps must match plan titles")

        step_stages = {
            ExecutionProgressStage.STEP_RUNNING,
            ExecutionProgressStage.AWAITING_CONFIRMATION,
            ExecutionProgressStage.STEP_COMPLETED,
            ExecutionProgressStage.STEP_SKIPPED,
            ExecutionProgressStage.STEP_FAILED,
        }
        if stage in step_stages and (
            self.total_steps == 0 or self.current_step == 0
        ):
            raise ExecutionProgressError("step events require a non-empty plan")

        elapsed = self.elapsed_seconds
        if elapsed is not None:
            if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)):
                raise ExecutionProgressError("elapsed_seconds must be a number")
            elapsed = float(elapsed)
            if elapsed < 0 or not math.isfinite(elapsed):
                raise ExecutionProgressError("elapsed_seconds must be finite and non-negative")

        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "title", safe_progress_title(self.title))
        object.__setattr__(self, "plan_titles", titles)
        object.__setattr__(self, "elapsed_seconds", elapsed)


__all__ = [
    "ExecutionProgressError",
    "ExecutionProgressEvent",
    "ExecutionProgressStage",
    "MAX_PROGRESS_TITLE_CHARS",
    "safe_progress_title",
]
