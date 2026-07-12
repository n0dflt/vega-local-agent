import unittest

from core.intent_router import (
    ConfirmationDecision,
    IntentKind,
    IntentRouter,
)


class IntentRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = IntentRouter()

    def test_empty_input_is_routed_as_empty(self) -> None:
        intent = self.router.route("   ")

        self.assertEqual(
            intent.kind,
            IntentKind.EMPTY,
        )
        self.assertTrue(intent.is_empty)
        self.assertEqual(
            intent.normalized_text,
            "",
        )

    def test_regular_text_is_routed_as_chat(self) -> None:
        intent = self.router.route(
            "  Исправь ошибку в проекте  "
        )

        self.assertEqual(
            intent.kind,
            IntentKind.CHAT,
        )
        self.assertTrue(intent.is_chat)
        self.assertEqual(
            intent.normalized_text,
            "Исправь ошибку в проекте",
        )

    def test_ordinary_coding_text_suggests_workflows(self) -> None:
        cases = {
            "Implement new feature for export": "feature",
            "Fix parser error": "bugfix",
            "Refactor parser without changing behavior": "refactor",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                intent = self.router.route(text)
                self.assertEqual(intent.suggested_workflow, expected)
                self.assertFalse(intent.workflow_selection_required)

    def test_ambiguous_coding_text_requires_selection(self) -> None:
        intent = self.router.route("Refactor parser and add new feature")
        self.assertIsNone(intent.suggested_workflow)
        self.assertTrue(intent.workflow_selection_required)
        self.assertEqual(set(intent.workflow_candidates), {"feature", "refactor"})

    def test_command_is_routed_as_command(self) -> None:
        intent = self.router.route(
            "/status"
        )

        self.assertEqual(
            intent.kind,
            IntentKind.COMMAND,
        )
        self.assertTrue(intent.is_command)
        self.assertEqual(
            intent.command_name,
            "/status",
        )
        self.assertEqual(
            intent.command_arguments,
            "",
        )

    def test_command_name_is_normalized(self) -> None:
        intent = self.router.route(
            "/STATUS"
        )

        self.assertEqual(
            intent.command_name,
            "/status",
        )

    def test_command_arguments_are_preserved(self) -> None:
        intent = self.router.route(
            "  /task new   Добавить оркестратор  "
        )

        self.assertEqual(
            intent.kind,
            IntentKind.COMMAND,
        )
        self.assertEqual(
            intent.command_name,
            "/task",
        )
        self.assertEqual(
            intent.command_arguments,
            "new   Добавить оркестратор",
        )

    def test_confirm_is_confirmation_when_pending(self) -> None:
        intent = self.router.route(
            " confirm ",
            confirmation_pending=True,
        )

        self.assertEqual(
            intent.kind,
            IntentKind.CONFIRMATION,
        )
        self.assertTrue(intent.is_confirmation)
        self.assertEqual(
            intent.confirmation_decision,
            ConfirmationDecision.CONFIRM,
        )

    def test_cancel_is_confirmation_when_pending(self) -> None:
        intent = self.router.route(
            "CANCEL",
            confirmation_pending=True,
        )

        self.assertEqual(
            intent.kind,
            IntentKind.CONFIRMATION,
        )
        self.assertEqual(
            intent.confirmation_decision,
            ConfirmationDecision.CANCEL,
        )

    def test_confirm_is_chat_without_pending_confirmation(self) -> None:
        intent = self.router.route(
            "CONFIRM",
            confirmation_pending=False,
        )

        self.assertEqual(
            intent.kind,
            IntentKind.CHAT,
        )
        self.assertIsNone(
            intent.confirmation_decision,
        )

    def test_command_has_priority_over_chat(self) -> None:
        intent = self.router.route(
            "/release check"
        )

        self.assertFalse(intent.is_chat)
        self.assertTrue(intent.is_command)
        self.assertEqual(
            intent.command_name,
            "/release",
        )

    def test_non_string_input_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            self.router.route(None)


if __name__ == "__main__":
    unittest.main()
