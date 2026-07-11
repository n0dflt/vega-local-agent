import json
import tempfile
import unittest
from pathlib import Path

from tools.doc_tools import (
    check_documentation,
    get_documentation_status,
    load_documentation_policy,
)
from tools.registry import get_tool


class DocumentationToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

        (self.root / "config").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "scripts").mkdir()

        (self.root / "scripts" / "version.py").write_text(
            'VERSION = "v1.9.0"\n',
            encoding="utf-8",
        )

        (self.root / "docs" / "architecture.md").write_text(
            "# Architecture\n",
            encoding="utf-8",
        )
        (self.root / "docs" / "commands.md").write_text(
            "# Commands\n",
            encoding="utf-8",
        )
        (self.root / "docs" / "security.md").write_text(
            "# Security\n",
            encoding="utf-8",
        )
        (self.root / "docs" / "roadmap.md").write_text(
            "# Roadmap\n",
            encoding="utf-8",
        )
        (self.root / "README.md").write_text(
            "# VEGA v1.9.0\n",
            encoding="utf-8",
        )
        (self.root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## v1.9.0\n",
            encoding="utf-8",
        )

        self.policy = {
            "schema_version": 1,
            "managed_documents": [
                {
                    "id": "architecture",
                    "path": "docs/architecture.md",
                    "generator": "architecture",
                    "required": True,
                },
                {
                    "id": "commands",
                    "path": "docs/commands.md",
                    "generator": "commands",
                    "required": True,
                },
                {
                    "id": "security",
                    "path": "docs/security.md",
                    "generator": "security",
                    "required": True,
                },
            ],
            "manual_documents": [
                {
                    "id": "readme",
                    "path": "README.md",
                    "required": True,
                    "check_version": True,
                },
                {
                    "id": "changelog",
                    "path": "CHANGELOG.md",
                    "required": True,
                    "check_version": True,
                },
                {
                    "id": "roadmap",
                    "path": "docs/roadmap.md",
                    "required": True,
                    "check_version": False,
                },
            ],
            "build_policy": {
                "create_missing_files": False,
                "use_patch_tools": True,
                "apply_automatically": False,
                "require_confirm_token": True,
            },
            "limits": {
                "max_document_chars": 100000,
                "max_generated_documents": 10,
            },
        }

        self._write_policy()

    def tearDown(self):
        self.temporary.cleanup()

    def _write_policy(self):
        policy_path = (
            self.root
            / "config"
            / "documentation_policy.json"
        )
        policy_path.write_text(
            json.dumps(self.policy, indent=2),
            encoding="utf-8",
        )

    def test_valid_policy_loads(self):
        result = load_documentation_policy(self.root)

        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(
            result["data"]["path"],
            "config/documentation_policy.json",
        )
        self.assertEqual(
            len(
                result["data"]["policy"][
                    "managed_documents"
                ]
            ),
            3,
        )

    def test_status_lists_all_documents(self):
        result = get_documentation_status(self.root)

        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(
            result["data"]["version"],
            "v1.9.0",
        )
        self.assertEqual(
            result["data"]["managed_count"],
            3,
        )
        self.assertEqual(
            result["data"]["manual_count"],
            3,
        )
        self.assertEqual(
            len(result["data"]["documents"]),
            6,
        )
        self.assertTrue(
            all(
                document["exists"]
                for document in result["data"]["documents"]
            )
        )

    def test_documentation_check_passes(self):
        result = check_documentation(self.root)

        self.assertTrue(result["ok"], result["error"])
        self.assertTrue(result["data"]["passed"])
        self.assertEqual(
            result["data"]["error_count"],
            0,
        )
        self.assertEqual(
            result["data"]["issues"],
            [],
        )

    def test_missing_required_document_fails(self):
        (
            self.root
            / "docs"
            / "security.md"
        ).unlink()

        result = check_documentation(self.root)

        self.assertTrue(result["ok"], result["error"])
        self.assertFalse(result["data"]["passed"])
        self.assertEqual(
            result["data"]["error_count"],
            1,
        )
        self.assertEqual(
            result["data"]["issues"][0]["document_id"],
            "security",
        )
        self.assertIn(
            "missing",
            result["data"]["issues"][0][
                "message"
            ].lower(),
        )

    def test_stale_version_is_reported(self):
        (self.root / "README.md").write_text(
            "# VEGA v1.8.0\n",
            encoding="utf-8",
        )

        result = check_documentation(self.root)

        self.assertTrue(result["ok"], result["error"])
        self.assertFalse(result["data"]["passed"])

        readme_issue = next(
            issue
            for issue in result["data"]["issues"]
            if issue["document_id"] == "readme"
        )

        self.assertIn(
            "v1.9.0",
            readme_issue["message"],
        )

    def test_automatic_application_is_rejected(self):
        self.policy["build_policy"][
            "apply_automatically"
        ] = True
        self._write_policy()

        result = load_documentation_policy(self.root)

        self.assertFalse(result["ok"])
        self.assertIn(
            "Automatic documentation patch application",
            result["error"],
        )

    def test_documentation_tools_are_registered(self):
        self.assertIs(
            get_tool("documentation_policy_load"),
            load_documentation_policy,
        )
        self.assertIs(
            get_tool("documentation_status"),
            get_documentation_status,
        )
        self.assertIs(
            get_tool("documentation_check"),
            check_documentation,
        )


if __name__ == "__main__":
    unittest.main()
