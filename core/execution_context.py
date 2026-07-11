"""Shared execution state for one VEGA runtime session."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.agent_modes import ModeSession
from core.confirmation_manager import ConfirmationManager


_ALLOWED_MESSAGE_ROLES = frozenset(
    {
        "system",
        "user",
        "assistant",
    }
)


@dataclass(slots=True)
class ExecutionContext:
    """Store runtime state shared by VEGA orchestration components."""

    project_root: Path
    model: str
    log_file: Path
    system_prompt: str
    mode_session: ModeSession
    confirmation_manager: ConfirmationManager = field(
        default_factory=ConfirmationManager
    )
    messages: list[dict[str, str]] = field(default_factory=list)
    memory_warning_errors: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        """Normalize and validate the initial session state."""
        self.project_root = Path(self.project_root).resolve()

        log_path = Path(self.log_file)
        if not log_path.is_absolute():
            log_path = self.project_root / log_path
        self.log_file = log_path.resolve()

        self.model = self._validate_text(self.model, "Model")
        self.system_prompt = self._validate_text(
            self.system_prompt,
            "System prompt",
        )

        if not isinstance(self.mode_session, ModeSession):
            raise TypeError("mode_session must be a ModeSession instance.")

        if not isinstance(
            self.confirmation_manager,
            ConfirmationManager,
        ):
            raise TypeError(
                "confirmation_manager must be a "
                "ConfirmationManager instance."
            )

        if not self.messages:
            self.messages.append(
                {
                    "role": "system",
                    "content": self.system_prompt,
                }
            )

        self._validate_messages()

    @property
    def active_mode_name(self) -> str:
        """Return the currently active VEGA mode name."""
        return self.mode_session.active_mode_name

    @property
    def confirmation_pending(self) -> bool:
        """Return whether the session awaits user confirmation."""
        return self.confirmation_manager.has_pending

    def set_model(self, model: str) -> None:
        """Update the model used by the current session."""
        self.model = self._validate_text(model, "Model")

    def append_message(self, role: str, content: str) -> None:
        """Append one validated chat message to session history."""
        normalized_role = self._validate_text(role, "Message role").lower()

        if normalized_role not in _ALLOWED_MESSAGE_ROLES:
            allowed = ", ".join(sorted(_ALLOWED_MESSAGE_ROLES))
            raise ValueError(
                f"Unsupported message role: {role!r}. "
                f"Allowed roles: {allowed}."
            )

        normalized_content = self._validate_text(
            content,
            "Message content",
        )

        self.messages.append(
            {
                "role": normalized_role,
                "content": normalized_content,
            }
        )

    def copy_messages(self) -> list[dict[str, str]]:
        """Return a detached copy of the current chat history."""
        return [dict(message) for message in self.messages]

    def _validate_messages(self) -> None:
        if not isinstance(self.messages, list):
            raise TypeError("messages must be a list.")

        for index, message in enumerate(self.messages):
            if not isinstance(message, dict):
                raise TypeError(
                    f"Message at index {index} must be a dictionary."
                )

            role = message.get("role")
            content = message.get("content")

            if role not in _ALLOWED_MESSAGE_ROLES:
                raise ValueError(
                    f"Message at index {index} has an invalid role."
                )

            if not isinstance(content, str) or not content.strip():
                raise ValueError(
                    f"Message at index {index} has empty content."
                )

        first_message = self.messages[0]

        if first_message["role"] != "system":
            raise ValueError(
                "The first execution-context message must use "
                "the system role."
            )

    @staticmethod
    def _validate_text(value: str, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string.")

        normalized = value.strip()

        if not normalized:
            raise ValueError(f"{field_name} must not be empty.")

        return normalized
