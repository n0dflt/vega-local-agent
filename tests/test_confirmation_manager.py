import unittest

from core.confirmation_manager import (
    ConfirmationManager,
    ConfirmationResolution,
    ConfirmationStateError,
)
from core.intent_router import ConfirmationDecision


class ConfirmationManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ConfirmationManager()

    def test_manager_starts_without_pending_request(self) -> None:
        self.assertFalse(self.manager.has_pending)
        self.assertIsNone(self.manager.pending)

    def test_request_registers_pending_action(self) -> None:
        request = self.manager.request(
            "  patch-1  ",
            "  apply_patch  ",
            "  Apply the patch?  ",
            payload={
                "patch_id": "patch-1",
            },
        )

        self.assertTrue(self.manager.has_pending)
        self.assertIs(
            self.manager.pending,
            request,
        )
        self.assertEqual(
            request.action_id,
            "patch-1",
        )
        self.assertEqual(
            request.action_name,
            "apply_patch",
        )
        self.assertEqual(
            request.prompt,
            "Apply the patch?",
        )
        self.assertEqual(
            request.payload,
            {
                "patch_id": "patch-1",
            },
        )

    def test_request_copies_payload(self) -> None:
        payload = {
            "patch_id": "patch-1",
        }

        request = self.manager.request(
            "patch-1",
            "apply_patch",
            "Apply the patch?",
            payload=payload,
        )

        payload["patch_id"] = "changed"

        self.assertEqual(
            request.payload["patch_id"],
            "patch-1",
        )

    def test_second_pending_request_is_rejected(self) -> None:
        self.manager.request(
            "first",
            "first_action",
            "Confirm first action?",
        )

        with self.assertRaises(
            ConfirmationStateError
        ):
            self.manager.request(
                "second",
                "second_action",
                "Confirm second action?",
            )

    def test_confirm_resolves_and_clears_request(self) -> None:
        request = self.manager.request(
            "patch-1",
            "apply_patch",
            "Apply the patch?",
        )

        result = self.manager.resolve(
            ConfirmationDecision.CONFIRM
        )

        self.assertEqual(
            result.resolution,
            ConfirmationResolution.CONFIRMED,
        )
        self.assertTrue(result.confirmed)
        self.assertFalse(result.cancelled)
        self.assertIs(
            result.request,
            request,
        )
        self.assertFalse(self.manager.has_pending)

    def test_cancel_resolves_and_clears_request(self) -> None:
        request = self.manager.request(
            "patch-1",
            "apply_patch",
            "Apply the patch?",
        )

        result = self.manager.resolve(
            ConfirmationDecision.CANCEL
        )

        self.assertEqual(
            result.resolution,
            ConfirmationResolution.CANCELLED,
        )
        self.assertFalse(result.confirmed)
        self.assertTrue(result.cancelled)
        self.assertIs(
            result.request,
            request,
        )
        self.assertFalse(self.manager.has_pending)

    def test_resolve_without_pending_request_is_rejected(self) -> None:
        with self.assertRaises(
            ConfirmationStateError
        ):
            self.manager.resolve(
                ConfirmationDecision.CONFIRM
            )

    def test_invalid_resolution_decision_is_rejected(self) -> None:
        self.manager.request(
            "patch-1",
            "apply_patch",
            "Apply the patch?",
        )

        with self.assertRaises(TypeError):
            self.manager.resolve("CONFIRM")

        self.assertTrue(self.manager.has_pending)

    def test_clear_returns_previous_request(self) -> None:
        request = self.manager.request(
            "patch-1",
            "apply_patch",
            "Apply the patch?",
        )

        cleared = self.manager.clear()

        self.assertIs(
            cleared,
            request,
        )
        self.assertFalse(self.manager.has_pending)

    def test_clear_without_pending_request_returns_none(self) -> None:
        self.assertIsNone(
            self.manager.clear()
        )

    def test_invalid_request_values_are_rejected(self) -> None:
        invalid_values = (
            {
                "action_id": "",
                "action_name": "action",
                "prompt": "Confirm?",
            },
            {
                "action_id": "id",
                "action_name": "   ",
                "prompt": "Confirm?",
            },
            {
                "action_id": "id",
                "action_name": "action",
                "prompt": "",
            },
        )

        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    self.manager.request(**values)

                self.assertFalse(
                    self.manager.has_pending
                )

    def test_non_dictionary_payload_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            self.manager.request(
                "patch-1",
                "apply_patch",
                "Apply the patch?",
                payload=["patch-1"],
            )

        self.assertFalse(self.manager.has_pending)


if __name__ == "__main__":
    unittest.main()
