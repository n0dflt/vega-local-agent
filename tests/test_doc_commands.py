import unittest
from unittest.mock import patch

from core.command_handler import (
    DOCGEN_HELP,
    handle_docgen_command,
)


class DocumentationCommandTests(unittest.TestCase):
    def test_docgen_without_arguments_shows_help(self):
        result = handle_docgen_command("/docgen")

        self.assertEqual(result, DOCGEN_HELP)
        self.assertIn("/docgen status", result)
        self.assertIn("/docgen check", result)

    def test_unknown_action_shows_help(self):
        result = handle_docgen_command(
            "/docgen unknown"
        )

        self.assertEqual(result, DOCGEN_HELP)

    def test_extra_arguments_show_help(self):
        result = handle_docgen_command(
            "/docgen status extra"
        )

        self.assertEqual(result, DOCGEN_HELP)

    @patch(
        "tools.doc_tools.get_documentation_status"
    )
    def test_status_output(
        self,
        get_documentation_status,
    ):
        get_documentation_status.return_value = {
            "ok": True,
            "error": None,
            "data": {
                "policy_path": (
                    "config/documentation_policy.json"
                ),
                "version": "v1.9.0",
                "managed_count": 1,
                "manual_count": 1,
                "documents": [
                    {
                        "id": "architecture",
                        "path": (
                            "docs/architecture.md"
                        ),
                        "kind": "managed",
                        "exists": True,
                        "version_current": None,
                    },
                    {
                        "id": "readme",
                        "path": "README.md",
                        "kind": "manual",
                        "exists": True,
                        "version_current": True,
                    },
                ],
            },
        }

        result = handle_docgen_command(
            "/docgen status"
        )

        self.assertIn(
            "Documentation Builder status",
            result,
        )
        self.assertIn(
            "Project version: v1.9.0",
            result,
        )
        self.assertIn(
            "[OK] architecture",
            result,
        )
        self.assertIn(
            "version: current",
            result,
        )

        get_documentation_status.assert_called_once_with(
            None
        )

    @patch(
        "tools.doc_tools.get_documentation_status"
    )
    def test_status_error_is_controlled(
        self,
        get_documentation_status,
    ):
        get_documentation_status.return_value = {
            "ok": False,
            "error": "Policy could not be loaded.",
            "data": None,
        }

        result = handle_docgen_command(
            "/docgen status"
        )

        self.assertIn(
            "Documentation command error",
            result,
        )
        self.assertIn(
            "Policy could not be loaded",
            result,
        )

    @patch(
        "tools.doc_tools.check_documentation"
    )
    def test_check_pass_output(
        self,
        check_documentation,
    ):
        check_documentation.return_value = {
            "ok": True,
            "error": None,
            "data": {
                "passed": True,
                "version": "v1.9.0",
                "error_count": 0,
                "issues": [],
            },
        }

        result = handle_docgen_command(
            "/docgen check"
        )

        self.assertIn(
            "Documentation check",
            result,
        )
        self.assertIn(
            "Status: PASS",
            result,
        )
        self.assertIn(
            "Errors: 0",
            result,
        )
        self.assertIn(
            "No documentation issues found.",
            result,
        )

    @patch(
        "tools.doc_tools.check_documentation"
    )
    def test_check_fail_output(
        self,
        check_documentation,
    ):
        check_documentation.return_value = {
            "ok": True,
            "error": None,
            "data": {
                "passed": False,
                "version": "v1.9.0",
                "error_count": 1,
                "issues": [
                    {
                        "severity": "error",
                        "document_id": "security",
                        "path": "docs/security.md",
                        "message": (
                            "Required documentation "
                            "file is missing."
                        ),
                    },
                ],
            },
        }

        result = handle_docgen_command(
            "/docgen check"
        )

        self.assertIn(
            "Status: FAIL",
            result,
        )
        self.assertIn(
            "Errors: 1",
            result,
        )
        self.assertIn(
            "[ERROR] docs/security.md",
            result,
        )
        self.assertIn(
            "Required documentation file is missing.",
            result,
        )


if __name__ == "__main__":
    unittest.main()
