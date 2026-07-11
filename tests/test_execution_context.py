import tempfile
import unittest
from pathlib import Path

from core.agent_modes import ModeRegistry, ModeSession
from core.execution_context import ExecutionContext


class ExecutionContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

        self.project_root = Path(
            self.temporary_directory.name
        ).resolve()

        self.mode_session = ModeSession(
            ModeRegistry()
        )

    def create_context(
        self,
        **overrides,
    ) -> ExecutionContext:
        values = {
            "project_root": self.project_root,
            "model": "test-model",
            "log_file": Path("logs") / "test.log",
            "system_prompt": "Test system prompt",
            "mode_session": self.mode_session,
        }
        values.update(overrides)

        return ExecutionContext(**values)

    def test_context_initializes_system_message(self) -> None:
        context = self.create_context()

        self.assertEqual(
            context.messages,
            [
                {
                    "role": "system",
                    "content": "Test system prompt",
                }
            ],
        )

    def test_context_normalizes_project_and_log_paths(self) -> None:
        context = self.create_context()

        self.assertEqual(
            context.project_root,
            self.project_root,
        )
        self.assertEqual(
            context.log_file,
            (
                self.project_root
                / "logs"
                / "test.log"
            ).resolve(),
        )

    def test_context_reports_active_mode(self) -> None:
        context = self.create_context()

        self.assertEqual(
            context.active_mode_name,
            "coder",
        )

        self.mode_session.set_mode("reviewer")

        self.assertEqual(
            context.active_mode_name,
            "reviewer",
        )

    def test_set_model_updates_current_model(self) -> None:
        context = self.create_context()

        context.set_model("updated-model")

        self.assertEqual(
            context.model,
            "updated-model",
        )

    def test_append_message_normalizes_values(self) -> None:
        context = self.create_context()

        context.append_message(
            " USER ",
            " Test message ",
        )

        self.assertEqual(
            context.messages[-1],
            {
                "role": "user",
                "content": "Test message",
            },
        )

    def test_append_message_rejects_unknown_role(self) -> None:
        context = self.create_context()

        with self.assertRaises(ValueError):
            context.append_message(
                "tool",
                "Tool result",
            )

    def test_copy_messages_returns_detached_copy(self) -> None:
        context = self.create_context()
        copied_messages = context.copy_messages()

        copied_messages[0]["content"] = "Changed copy"
        copied_messages.append(
            {
                "role": "user",
                "content": "Extra message",
            }
        )

        self.assertEqual(
            context.messages,
            [
                {
                    "role": "system",
                    "content": "Test system prompt",
                }
            ],
        )

    def test_empty_model_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.create_context(
                model="   ",
            )

    def test_invalid_mode_session_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            self.create_context(
                mode_session=None,
            )

    def test_first_message_must_be_system_message(self) -> None:
        with self.assertRaises(ValueError):
            self.create_context(
                messages=[
                    {
                        "role": "user",
                        "content": "Invalid first message",
                    }
                ],
            )


    def test_context_creates_confirmation_manager(self) -> None:
        context = self.create_context()

        self.assertFalse(
            context.confirmation_pending
        )
        self.assertFalse(
            context.confirmation_manager.has_pending
        )

    def test_context_reports_pending_confirmation(self) -> None:
        context = self.create_context()

        context.confirmation_manager.request(
            "patch-1",
            "apply_patch",
            "Apply patch?",
        )

        self.assertTrue(
            context.confirmation_pending
        )

    def test_contexts_do_not_share_confirmation_state(self) -> None:
        first_context = self.create_context()
        second_context = self.create_context()

        first_context.confirmation_manager.request(
            "patch-1",
            "apply_patch",
            "Apply patch?",
        )

        self.assertTrue(
            first_context.confirmation_pending
        )
        self.assertFalse(
            second_context.confirmation_pending
        )

    def test_invalid_confirmation_manager_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            self.create_context(
                confirmation_manager=None,
            )


if __name__ == "__main__":
    unittest.main()
