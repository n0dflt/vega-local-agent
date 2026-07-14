import unittest
from pathlib import Path

from core.command_handler import handle_permissions_command
from core.confirmation_manager import ConfirmationManager
from core.tool_confirmation import ToolConfirmationManager
from permissions import (
    PermissionCapability,
    PermissionEffect,
    PermissionEvaluator,
    SessionGrantStore,
    load_permission_policy,
)
from scripts.version import VERSION
from tools.registry import TOOL_REGISTRY


ROOT = Path(__file__).resolve().parents[1]


class ReleaseV121Tests(unittest.TestCase):
    def test_version_identity_and_release_documentation_are_synchronized(self):
        self.assertEqual(VERSION, "v2.12.1")

        for relative in (
            "README.md",
            "CHANGELOG.md",
            "docs/roadmap.md",
        ):
            with self.subTest(relative=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("v2.12.1", text)

    def test_apache_license_files_exist(self):
        license_path = ROOT / "LICENSE"
        notice_path = ROOT / "NOTICE"

        self.assertTrue(license_path.is_file())
        self.assertTrue(notice_path.is_file())

        license_text = license_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        notice_text = notice_path.read_text(encoding="utf-8")

        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0", license_text)
        self.assertIn("Copyright 2026 n0dflt", notice_text)
        self.assertIn("Apache License", notice_text)

    def test_readme_declares_apache_license(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Apache License", readme)
        self.assertIn("LICENSE", readme)
        self.assertIn("NOTICE", readme)

    def test_production_policy_loads_and_exactly_classifies_registry(self):
        policy = load_permission_policy(
            ROOT,
            registered_tools=TOOL_REGISTRY,
        )

        self.assertEqual(
            {rule.tool_name for rule in policy.rules},
            set(TOOL_REGISTRY),
        )
        self.assertIs(policy.default_effect, PermissionEffect.DENY)

    def test_missing_rules_fail_closed_and_capabilities_are_closed_vocabulary(
        self,
    ):
        policy = load_permission_policy(ROOT)
        decision = PermissionEvaluator(policy).evaluate(
            "not_registered"
        )

        self.assertIs(decision.effect, PermissionEffect.DENY)
        self.assertTrue(decision.error_code)

        with self.assertRaises(ValueError):
            PermissionCapability("arbitrary.capability")

    def test_session_restricted_tools_cannot_gain_authorization(self):
        policy = load_permission_policy(ROOT)

        restricted = {
            rule.tool_name
            for rule in policy.rules
            if rule.effect is PermissionEffect.CONFIRM
            and not rule.session_grant_allowed
        }

        self.assertEqual(
            restricted,
            {
                "apply_patch",
                "documentation_build",
                "internet_set",
                "release_check",
                "rollback_patch",
                "terminal_run",
                "test_run",
                "web_fetch",
            },
        )

    def test_grants_start_empty_routes_exist_and_confirmations_are_separate(
        self,
    ):
        store = SessionGrantStore()

        self.assertEqual(store.list_grants(), ())
        self.assertIn(
            "/permissions grants",
            handle_permissions_command("/permissions", store),
        )
        self.assertEqual(
            handle_permissions_command(
                "/permissions grants",
                store,
            ),
            "Active session grants: none.",
        )
        self.assertIsNot(
            ConfirmationManager,
            ToolConfirmationManager,
        )

    def test_documentation_contains_no_known_mojibake_markers(self):
        markers = (
            "вЂ",
            "Рџ",
            "â€",
            "Ã",
        )

        for relative in (
            "README.md",
            "docs/roadmap.md",
        ):
            with self.subTest(relative=relative):
                text = (ROOT / relative).read_text(
                    encoding="utf-8"
                )

                for marker in markers:
                    self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
