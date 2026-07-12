import tempfile
import shutil
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
        (self.project_root / "config").mkdir()
        shutil.copy(
            Path(__file__).parents[1] / "config" / "checkpoint_policy.json",
            self.project_root / "config" / "checkpoint_policy.json",
        )

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


    def test_chat_input_is_routed_without_history_mutation(
        self,
    ) -> None:
        result = self.orchestrator.process(
            "  Analyze the project  "
        )

        self.assertEqual(
            result.kind,
            OrchestrationKind.CHAT,
        )
        self.assertTrue(
            result.should_call_model
        )
        self.assertEqual(
            result.intent.normalized_text,
            "Analyze the project",
        )
        self.assertEqual(
            len(self.context.messages),
            1,
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


    def test_confirm_without_pending_action_is_chat(
        self,
    ) -> None:
        result = self.orchestrator.process(
            "CONFIRM"
        )

        self.assertEqual(
            result.kind,
            OrchestrationKind.CHAT,
        )
        self.assertEqual(
            result.intent.normalized_text,
            "CONFIRM",
        )
        self.assertEqual(
            len(self.context.messages),
            1,
        )

    def test_invalid_context_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            AgentOrchestrator(None)


    def test_coding_workflow_suggestion_is_visible(self) -> None:
        result = self.orchestrator.process("Fix parser error")
        self.assertEqual(result.intent.suggested_workflow, "bugfix")
        self.assertIn("bugfix", result.message)

    def test_ambiguous_coding_request_asks_for_choice(self) -> None:
        result = self.orchestrator.process("Refactor parser and add new feature")
        self.assertTrue(result.intent.workflow_selection_required)
        self.assertIn("Choose workflow", result.message)

    def test_ordinary_coding_text_creates_read_only_draft(self) -> None:
        from workflows import WorkflowEngine, default_registry
        from workflows.models import WorkflowStatus

        engine = WorkflowEngine(self.project_root, default_registry())
        orchestrator = AgentOrchestrator(self.context, workflow_engine=engine)
        result = orchestrator.process("Fix parser error")
        self.assertEqual(result.kind, OrchestrationKind.WORKFLOW_DRAFT)
        self.assertEqual(result.workflow_run.status, WorkflowStatus.WAITING_PATCH)
        self.assertIsNone(result.workflow_run.patch)

    def test_ambiguous_text_does_not_create_draft(self) -> None:
        from workflows import WorkflowEngine, default_registry

        engine = WorkflowEngine(self.project_root, default_registry())
        orchestrator = AgentOrchestrator(self.context, workflow_engine=engine)
        result = orchestrator.process("Refactor parser and add new feature")
        self.assertEqual(result.kind, OrchestrationKind.CHAT)
        self.assertIsNone(engine.status())


if __name__ == "__main__":
    unittest.main()
