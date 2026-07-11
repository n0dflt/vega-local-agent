"""Top-level deterministic orchestration for one VEGA session."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.command_router import CommandRoute, CommandRouter
from core.confirmation_manager import ConfirmationResult
from core.execution_context import ExecutionContext
from core.intent_router import (
    IntentKind,
    IntentRouter,
    RoutedIntent,
)


class OrchestrationKind(str, Enum):
    """Supported top-level orchestration outcomes."""

    EMPTY = "empty"
    CHAT = "chat"
    COMMAND = "command"
    CONFIRMATION = "confirmation"
    WAITING_CONFIRMATION = "waiting_confirmation"


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Describe the result of processing one user input."""

    kind: OrchestrationKind
    intent: RoutedIntent
    command_route: CommandRoute | None = None
    confirmation_result: ConfirmationResult | None = None
    message: str = ""

    @property
    def should_call_model(self) -> bool:
        """Return whether the input should be sent to the model."""
        return self.kind is OrchestrationKind.CHAT

    @property
    def should_execute_command(self) -> bool:
        """Return whether a slash command was routed."""
        return self.kind is OrchestrationKind.COMMAND


class AgentOrchestrator:
    """Coordinate intent, command and confirmation routing."""

    def __init__(
        self,
        context: ExecutionContext,
        *,
        intent_router: IntentRouter | None = None,
        command_router: CommandRouter | None = None,
    ) -> None:
        if not isinstance(context, ExecutionContext):
            raise TypeError(
                "context must be an ExecutionContext instance."
            )

        if (
            intent_router is not None
            and not isinstance(intent_router, IntentRouter)
        ):
            raise TypeError(
                "intent_router must be an IntentRouter instance."
            )

        if (
            command_router is not None
            and not isinstance(command_router, CommandRouter)
        ):
            raise TypeError(
                "command_router must be a CommandRouter instance."
            )

        self.context = context
        self.intent_router = intent_router or IntentRouter()
        self.command_router = command_router or CommandRouter()

    def process(self, text: str) -> OrchestrationResult:
        """Process one raw user input without invoking the model."""
        intent = self.intent_router.route(
            text,
            confirmation_pending=self.context.confirmation_pending,
        )

        if intent.kind is IntentKind.EMPTY:
            return OrchestrationResult(
                kind=OrchestrationKind.EMPTY,
                intent=intent,
            )

        if intent.kind is IntentKind.CONFIRMATION:
            decision = intent.confirmation_decision

            if decision is None:
                raise RuntimeError(
                    "Confirmation intent has no decision."
                )

            confirmation_result = (
                self.context.confirmation_manager.resolve(
                    decision
                )
            )

            return OrchestrationResult(
                kind=OrchestrationKind.CONFIRMATION,
                intent=intent,
                confirmation_result=confirmation_result,
            )

        if intent.kind is IntentKind.COMMAND:
            command_route = self.command_router.route(
                intent
            )

            return OrchestrationResult(
                kind=OrchestrationKind.COMMAND,
                intent=intent,
                command_route=command_route,
            )

        if self.context.confirmation_pending:
            return OrchestrationResult(
                kind=(
                    OrchestrationKind
                    .WAITING_CONFIRMATION
                ),
                intent=intent,
                message=(
                    "An action is waiting for confirmation. "
                    "Enter CONFIRM or CANCEL."
                ),
            )

        if intent.kind is IntentKind.CHAT:
            return OrchestrationResult(
                kind=OrchestrationKind.CHAT,
                intent=intent,
            )

        raise RuntimeError(
            f"Unsupported intent kind: {intent.kind!r}."
        )

