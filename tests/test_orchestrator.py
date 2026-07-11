import tempfile
import unittest
from pathlib import Path

from core.agent_modes import ModeRegistry, ModeSession
from core.command_router import CommandTarget
from core.execution_context import ExecutionContext
from core.orchestrator import (
    AgentOrchestrator,
    OrchestrationKind,
)


class AgentOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

        self.project_root = Path(
            self.temporary_directory.name
        ).resolve()

        mode_session = ModeSession(
            ModeRegistry()
        )

        self.context = ExecutionContext(
            project_root=self.project_root,
            model="test-model",
            log_file=Path("logs") / "test.log",
            system_prompt="Test system prompt",
            mode_session=mode_session,
        )

        self.orchestrator = AgentOrchestrator(
            self.context
        )

    def test_empty_input_returns_empty_result(self) -> None:
        result = self.orchestrator.process("   ")

        self.assertEqual(
            result.kind,
            OrchestrationKind.EMPTY,
        )
        self.assertFalse(result.should_call_model)
        self.assertEqual(
            len(self.context.messages),
            1,
        )

    def test_chat_input_is_added_to_history(self) -> None:
        result = self.orchestrator.process(
            "  Analyze the project  "
        )

        self.assertEqual(
            result.kind,
            OrchestrationKind.CHAT,
        )
        self.assertTrue(result.should_call_model)
        self.assertEqual(
            self.context.messages[-1],
            {
                "role": "user",
                "content": "Analyze the project",
            },
        )

    def test_command_is_routed_without_chat_mutation(self) -> None:
        result = self.orchestrator.process(
            "/status"
        )

        self.assertEqual(
            result.kind,
            OrchestrationKind.COMMAND,
        )
        self.assertTrue(
            result.should_execute_command
        )
        self.assertEqual(
            result.command_route.target,
            CommandTarget.STATUS,
        )
        self.assertEqual(
            len(self.context.messages),
            1,
        )

    def test_unknown_command_is_still_command_result(self) -> None:
        result = self.orchestrator.process(
            "/unknown"
        )

        self.assertEqual(
            result.kind,
            OrchestrationKind.COMMAND,
        )
        self.assertEqual(
            result.command_route.target,
            CommandTarget.UNKNOWN,
        )

    def test_confirm_resolves_pending_action(self) -> None:
        self.context.confirmation_manager.request(
            "patch-1",
            "apply_patch",
            "Apply patch?",
        )

        result = self.orchestrator.process(
            "CONFIRM"
        )

        self.assertEqual(
            result.kind,
            OrchestrationKind.CONFIRMATION,
        )
        self.assertTrue(
            result.confirmation_result.confirmed
        )
        self.assertFalse(
            self.context.confirmation_pending
        )

    def test_cancel_resolves_pending_action(self) -> None:
        self.context.confirmation_manager.request(
            "patch-1",
            "apply_patch",
            "Apply patch?",
        )

        result = self.orchestrator.process(
            "cancel"
        )

        self.assertEqual(
            result.kind,
            OrchestrationKind.CONFIRMATION,
        )
        self.assertTrue(
            result.confirmation_result.cancelled
        )
        self.assertFalse(
            self.context.confirmation_pending
        )

    def test_chat_is_blocked_while_confirmation_pending(
        self,
    ) -> None:
        self.context.confirmation_manager.request(
            "patch-1",
            "apply_patch",
            "Apply patch?",
        )

        result = self.orchestrator.process(
            "Continue with another task"
        )

        self.assertEqual(
            result.kind,
            OrchestrationKind.WAITING_CONFIRMATION,
        )
        self.assertIn(
            "CONFIRM or CANCEL",
            result.message,
        )
        self.assertEqual(
            len(self.context.messages),
            1,
        )
        self.assertTrue(
            self.context.confirmation_pending
        )

    def test_command_is_allowed_while_confirmation_pending(
        self,
    ) -> None:
        self.context.confirmation_manager.request(
            "patch-1",
            "apply_patch",
            "Apply patch?",
        )

        result = self.orchestrator.process(
            "/status"
        )

        self.assertEqual(
            result.kind,
            OrchestrationKind.COMMAND,
        )
        self.assertEqual(
            result.command_route.target,
            CommandTarget.STATUS,
        )
        self.assertTrue(
            self.context.confirmation_pending
        )

    def test_confirm_without_pending_action_is_chat(self) -> None:
        result = self.orchestrator.process(
            "CONFIRM"
        )

        self.assertEqual(
            result.kind,
            OrchestrationKind.CHAT,
        )
        self.assertEqual(
            self.context.messages[-1]["content"],
            "CONFIRM",
        )

    def test_invalid_context_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            AgentOrchestrator(None)


if __name__ == "__main__":
    unittest.main()
