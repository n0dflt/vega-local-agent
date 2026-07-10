"""Task status validation for the VEGA Project Control Layer."""

from __future__ import annotations

from enum import Enum
from typing import Final


class TaskStateError(ValueError):
    """A user-facing task state error."""


class TaskStatus(str, Enum):
    """Supported statuses of a VEGA project task."""

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    WAITING_REVIEW = "waiting_review"
    NEEDS_REWORK = "needs_rework"
    BLOCKED = "blocked"
    DONE = "done"


TERMINAL_STATUSES: Final[frozenset[TaskStatus]] = frozenset(
    {
        TaskStatus.DONE,
    }
)


_ALLOWED_TRANSITIONS: Final[
    dict[TaskStatus, frozenset[TaskStatus]]
] = {
    TaskStatus.PLANNED: frozenset(
        {
            TaskStatus.IN_PROGRESS,
            TaskStatus.BLOCKED,
        }
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {
            TaskStatus.WAITING_REVIEW,
            TaskStatus.NEEDS_REWORK,
            TaskStatus.BLOCKED,
        }
    ),
    TaskStatus.WAITING_REVIEW: frozenset(
        {
            TaskStatus.DONE,
            TaskStatus.NEEDS_REWORK,
            TaskStatus.BLOCKED,
        }
    ),
    TaskStatus.NEEDS_REWORK: frozenset(
        {
            TaskStatus.IN_PROGRESS,
            TaskStatus.BLOCKED,
        }
    ),
    TaskStatus.BLOCKED: frozenset(
        {
            TaskStatus.PLANNED,
            TaskStatus.IN_PROGRESS,
        }
    ),
    TaskStatus.DONE: frozenset(),
}


def normalize_status(
    value: TaskStatus | str,
) -> TaskStatus:
    """Convert a string into a validated TaskStatus."""

    if isinstance(value, TaskStatus):
        return value

    if not isinstance(value, str):
        raise TaskStateError(
            "Task status must be a string or TaskStatus."
        )

    normalized = value.strip().lower()

    if not normalized:
        raise TaskStateError(
            "Task status must not be empty."
        )

    try:
        return TaskStatus(normalized)
    except ValueError as exc:
        allowed = ", ".join(
            status.value
            for status in TaskStatus
        )

        raise TaskStateError(
            f"Unknown task status: {value!r}. "
            f"Allowed statuses: {allowed}."
        ) from exc


def allowed_transitions(
    current: TaskStatus | str,
) -> tuple[TaskStatus, ...]:
    """Return valid target statuses."""

    current_status = normalize_status(current)

    return tuple(
        status
        for status in TaskStatus
        if status in _ALLOWED_TRANSITIONS[current_status]
    )


def can_transition(
    current: TaskStatus | str,
    target: TaskStatus | str,
) -> bool:
    """Return whether the requested transition is allowed."""

    current_status = normalize_status(current)
    target_status = normalize_status(target)

    return target_status in _ALLOWED_TRANSITIONS[current_status]


def validate_transition(
    current: TaskStatus | str,
    target: TaskStatus | str,
) -> TaskStatus:
    """Validate a task status transition."""

    current_status = normalize_status(current)
    target_status = normalize_status(target)

    if current_status == target_status:
        raise TaskStateError(
            f"Task is already in status "
            f"{current_status.value!r}."
        )

    if target_status not in _ALLOWED_TRANSITIONS[current_status]:
        allowed = allowed_transitions(current_status)

        allowed_text = (
            ", ".join(
                status.value
                for status in allowed
            )
            if allowed
            else "none"
        )

        raise TaskStateError(
            f"Task cannot transition from "
            f"{current_status.value!r} to "
            f"{target_status.value!r}. "
            f"Allowed transitions: {allowed_text}."
        )

    return target_status


def is_terminal_status(
    value: TaskStatus | str,
) -> bool:
    """Return whether the task has reached a terminal state."""

    return normalize_status(value) in TERMINAL_STATUSES
