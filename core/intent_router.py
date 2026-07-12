"""Deterministic input classification for the VEGA orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IntentKind(str, Enum):
    """Supported top-level input routes."""

    EMPTY = "empty"
    COMMAND = "command"
    CHAT = "chat"
    CONFIRMATION = "confirmation"


class ConfirmationDecision(str, Enum):
    """Supported decisions for a pending confirmation request."""

    CONFIRM = "confirm"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class RoutedIntent:
    """Normalized result produced by the intent router."""

    kind: IntentKind
    raw_text: str
    normalized_text: str
    command_name: str | None = None
    command_arguments: str = ""
    confirmation_decision: ConfirmationDecision | None = None
    suggested_workflow: str | None = None
    workflow_candidates: tuple[str, ...] = ()
    workflow_selection_required: bool = False

    @property
    def is_empty(self) -> bool:
        """Return whether the routed input contains no actionable text."""
        return self.kind is IntentKind.EMPTY

    @property
    def is_command(self) -> bool:
        """Return whether the routed input is a slash command."""
        return self.kind is IntentKind.COMMAND

    @property
    def is_chat(self) -> bool:
        """Return whether the routed input should be sent to the model."""
        return self.kind is IntentKind.CHAT

    @property
    def is_confirmation(self) -> bool:
        """Return whether the routed input resolves a pending confirmation."""
        return self.kind is IntentKind.CONFIRMATION


class IntentRouter:
    """Classify raw user input without invoking a language model."""

    _CONFIRMATION_TOKENS = {
        "CONFIRM": ConfirmationDecision.CONFIRM,
        "CANCEL": ConfirmationDecision.CANCEL,
    }

    def route(
        self,
        text: str,
        *,
        confirmation_pending: bool = False,
    ) -> RoutedIntent:
        """Normalize and classify one user input value."""
        if not isinstance(text, str):
            raise TypeError("Intent text must be a string.")

        normalized_text = text.strip()

        if not normalized_text:
            return RoutedIntent(
                kind=IntentKind.EMPTY,
                raw_text=text,
                normalized_text="",
            )

        if confirmation_pending:
            decision = self._confirmation_decision(
                normalized_text,
            )

            if decision is not None:
                return RoutedIntent(
                    kind=IntentKind.CONFIRMATION,
                    raw_text=text,
                    normalized_text=normalized_text,
                    confirmation_decision=decision,
                )

        if normalized_text.startswith("/"):
            command_name, command_arguments = (
                self._parse_command(normalized_text)
            )

            return RoutedIntent(
                kind=IntentKind.COMMAND,
                raw_text=text,
                normalized_text=normalized_text,
                command_name=command_name,
                command_arguments=command_arguments,
            )

        suggested, candidates = self._classify_coding_workflow(normalized_text)
        return RoutedIntent(
            kind=IntentKind.CHAT,
            raw_text=text,
            normalized_text=normalized_text,
            suggested_workflow=suggested,
            workflow_candidates=candidates,
            workflow_selection_required=len(candidates) > 1,
        )

    @staticmethod
    def _classify_coding_workflow(text: str) -> tuple[str | None, tuple[str, ...]]:
        lowered = text.lower()
        keywords = {
            "feature": ("add ", "implement ", "new feature", "добав", "реализ", "новая функц"),
            "bugfix": ("bug", "fix ", "error", "broken", "ошиб", "баг", "исправ"),
            "refactor": ("refactor", "restructure", "without changing behavior", "рефактор", "без изменения поведения", "изменить структуру"),
        }
        matches = tuple(name for name, words in keywords.items() if any(word in lowered for word in words))
        return (matches[0] if len(matches) == 1 else None), matches

    @classmethod
    def _confirmation_decision(
        cls,
        text: str,
    ) -> ConfirmationDecision | None:
        return cls._CONFIRMATION_TOKENS.get(
            text.strip().upper()
        )

    @staticmethod
    def _parse_command(
        text: str,
    ) -> tuple[str, str]:
        command_name, separator, arguments = text.partition(" ")

        normalized_name = command_name.lower()
        normalized_arguments = (
            arguments.strip()
            if separator
            else ""
        )

        return normalized_name, normalized_arguments
