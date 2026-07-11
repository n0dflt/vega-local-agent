"""In-memory confirmation state for controlled VEGA actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.intent_router import ConfirmationDecision


class ConfirmationStateError(RuntimeError):
    """Raised when confirmation state cannot be changed safely."""


class ConfirmationResolution(str, Enum):
    """Final state of a resolved confirmation request."""

    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    """Describe one action waiting for explicit user confirmation."""

    action_id: str
    action_name: str
    prompt: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    """Describe the outcome of one resolved confirmation request."""

    resolution: ConfirmationResolution
    request: PendingConfirmation

    @property
    def confirmed(self) -> bool:
        """Return whether the user confirmed the pending action."""
        return self.resolution is ConfirmationResolution.CONFIRMED

    @property
    def cancelled(self) -> bool:
        """Return whether the user cancelled the pending action."""
        return self.resolution is ConfirmationResolution.CANCELLED


class ConfirmationManager:
    """Store at most one pending confirmation for a VEGA session."""

    def __init__(self) -> None:
        self._pending: PendingConfirmation | None = None

    @property
    def has_pending(self) -> bool:
        """Return whether an action currently awaits confirmation."""
        return self._pending is not None

    @property
    def pending(self) -> PendingConfirmation | None:
        """Return the current pending request without modifying it."""
        return self._pending

    def request(
        self,
        action_id: str,
        action_name: str,
        prompt: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> PendingConfirmation:
        """Register one action that requires explicit confirmation."""
        if self.has_pending:
            raise ConfirmationStateError(
                "Another action is already waiting for confirmation."
            )

        request = PendingConfirmation(
            action_id=self._validate_text(
                action_id,
                "Action id",
            ),
            action_name=self._validate_text(
                action_name,
                "Action name",
            ),
            prompt=self._validate_text(
                prompt,
                "Confirmation prompt",
            ),
            payload=self._validate_payload(payload),
        )

        self._pending = request
        return request

    def resolve(
        self,
        decision: ConfirmationDecision,
    ) -> ConfirmationResult:
        """Resolve and clear the current pending confirmation."""
        if not isinstance(decision, ConfirmationDecision):
            raise TypeError(
                "decision must be a ConfirmationDecision value."
            )

        request = self._require_pending()

        if decision is ConfirmationDecision.CONFIRM:
            resolution = ConfirmationResolution.CONFIRMED
        else:
            resolution = ConfirmationResolution.CANCELLED

        self._pending = None

        return ConfirmationResult(
            resolution=resolution,
            request=request,
        )

    def clear(self) -> PendingConfirmation | None:
        """Clear pending state without marking the action confirmed."""
        previous = self._pending
        self._pending = None
        return previous

    def _require_pending(self) -> PendingConfirmation:
        if self._pending is None:
            raise ConfirmationStateError(
                "No action is waiting for confirmation."
            )

        return self._pending

    @staticmethod
    def _validate_text(
        value: str,
        field_name: str,
    ) -> str:
        if not isinstance(value, str):
            raise TypeError(
                f"{field_name} must be a string."
            )

        normalized = value.strip()

        if not normalized:
            raise ValueError(
                f"{field_name} must not be empty."
            )

        return normalized

    @staticmethod
    def _validate_payload(
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if payload is None:
            return {}

        if not isinstance(payload, dict):
            raise TypeError(
                "Confirmation payload must be a dictionary."
            )

        return dict(payload)
