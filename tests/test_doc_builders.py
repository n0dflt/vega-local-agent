import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.command_handler import handle_docgen_command
from tools.doc_builders import (
    _discover_cli_commands,
    build_documentation,
)


class DocumentationBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

        for directory in (
            "config",
            "core",
            "docs",
            "scripts",
            "tools",
        ):
            (self.root / directory).mkdir()

        (self.root / "scripts" / "version.py").write_text(
            'VERSION = "v1.9.0"\n',
            encoding="utf-8",
        )

        (self.root / "scripts" / "vega.py").write_text(
            '''def help_text() -> str:
    return "\\n".join([
        "  /docgen status         Show documentation status.",
        "  /docgen check          Check documentation.",
        "  /docgen build          Create documentation patches.",
    ])


def print_available_commands() -> None:
    print("/docgen")
    print("/exit")
''',
            encoding="utf-8",
        )

        (self.root / "core" / "command_handler.py").write_text(
            "# command handler\n",
            encoding="utf-8",
        )
        (self.root / "tools" / "doc_tools.py").write_text(
            "# documentation tools\n",
            encoding="utf-8",
        )

        self.documents = {
            "docs/architecture.md": "# Architecture\n",
            "docs/commands.md": "# Commands\n",
            "docs/security.md": "# Security\n",
            "docs/roadmap.md": "# Roadmap\n",
            "README.md": "# VEGA v1.9.0\n",
            "CHANGELOG.md": "# Changelog\n\n## v1.9.0\n",
        }

        for relative_path, content in self.documents.items():
            path = self.root / relative_path
            path.write_text(
                content,
                encoding="utf-8",
            )

        policy = {
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

        (
            self.root
            / "config"
            / "documentation_policy.json"
        ).write_text(
            json.dumps(policy, indent=2),
            encoding="utf-8",
        )

        self.root_patcher = patch(
            "tools.doc_builders.get_project_root",
            return_value=self.root,
        )
        self.root_patcher.start()

    def tearDown(self):
        self.root_patcher.stop()
        self.temporary.cleanup()

    @staticmethod
    def _successful_patch(
        target_path,
        new_content,
        reason="",
    ):
        document_name = Path(target_path).stem

        return {
            "ok": True,
            "error": None,
            "data": {
                "patch_id": f"patch-{document_name}",
                "target_path": target_path,
                "status": "pending",
                "reason": reason,
                "diff": "test diff",
            },
        }

    @patch("tools.doc_builders.propose_patch")
    @patch("tools.doc_builders.list_patches")
    def test_build_creates_three_pending_patches(
        self,
        list_patches,
        propose_patch,
    ):
        list_patches.return_value = {
            "ok": True,
            "error": None,
            "data": [],
        }
        propose_patch.side_effect = self._successful_patch

        result = build_documentation(self.root)

        self.assertTrue(result["ok"], result["error"])
        self.assertTrue(result["data"]["passed"])
        self.assertEqual(
            result["data"]["created_count"],
            3,
        )
        self.assertEqual(
            result["data"]["error_count"],
            0,
        )
        self.assertFalse(
            result["data"]["applied_automatically"]
        )
        self.assertEqual(
            propose_patch.call_count,
            3,
        )

        targets = {
            call.kwargs["target_path"]
            for call in propose_patch.call_args_list
        }

        self.assertEqual(
            targets,
            {
                "docs/architecture.md",
                "docs/commands.md",
                "docs/security.md",
            },
        )

        for call in propose_patch.call_args_list:
            content = call.kwargs["new_content"]

            self.assertIn(
                "<!-- VEGA DOCGEN START:",
                content,
            )
            self.assertIn(
                "<!-- VEGA DOCGEN END:",
                content,
            )

    @patch("tools.doc_builders.propose_patch")
    @patch("tools.doc_builders.list_patches")
    def test_existing_pending_patch_is_skipped(
        self,
        list_patches,
        propose_patch,
    ):
        list_patches.return_value = {
            "ok": True,
            "error": None,
            "data": [
                {
                    "patch_id": "patch-existing",
                    "target_path": "docs/architecture.md",
                    "status": "pending",
                },
            ],
        }
        propose_patch.side_effect = self._successful_patch

        result = build_documentation(self.root)

        self.assertTrue(result["ok"], result["error"])
        self.assertTrue(result["data"]["passed"])
        self.assertEqual(
            result["data"]["created_count"],
            2,
        )
        self.assertEqual(
            result["data"]["skipped_count"],
            1,
        )
        self.assertEqual(
            result["data"]["skipped"][0]["reason"],
            "pending_patch_exists",
        )
        self.assertEqual(
            propose_patch.call_count,
            2,
        )

    @patch("tools.doc_builders.propose_patch")
    @patch("tools.doc_builders.list_patches")
    def test_missing_managed_document_blocks_build(
        self,
        list_patches,
        propose_patch,
    ):
        (
            self.root
            / "docs"
            / "security.md"
        ).unlink()

        list_patches.return_value = {
            "ok": True,
            "error": None,
            "data": [],
        }

        result = build_documentation(self.root)

        self.assertTrue(result["ok"], result["error"])
        self.assertFalse(result["data"]["passed"])
        self.assertEqual(
            result["data"]["created_count"],
            0,
        )
        self.assertEqual(
            result["data"]["error_count"],
            1,
        )
        self.assertEqual(
            result["data"]["errors"][0]["document_id"],
            "security",
        )
        propose_patch.assert_not_called()


    def test_command_discovery_normalizes_roots(self):
        (
            self.root
            / "scripts"
            / "vega.py"
        ).write_text(
            """def help_text() -> str:
    return "\\n".join([
        "  /patch                 Show patch help.",
        "  /git                   Show Git help.",
        "  /memory                Show memory help.",
        "  /docgen build          Create pending patches.",
        "  /project | /project status | /log | /clear",
    ])


def print_available_commands() -> None:
    print("/project status")
    print("/tools list")
    print("/docgen")
    print("/exit")
""",
            encoding="utf-8",
        )

        command_roots, help_entries = (
            _discover_cli_commands(self.root)
        )

        self.assertIn("/project", command_roots)
        self.assertIn("/tools", command_roots)
        self.assertIn("/patch", command_roots)
        self.assertIn("/git", command_roots)
        self.assertIn("/memory", command_roots)
        self.assertIn("/log", command_roots)
        self.assertIn("/clear", command_roots)

        self.assertNotIn(
            "/project status",
            command_roots,
        )
        self.assertNotIn(
            "/tools list",
            command_roots,
        )

        self.assertTrue(
            any(
                entry.startswith("/docgen build")
                for entry in help_entries
            )
        )

    def test_different_project_root_is_rejected(self):
        different_root = self.root / "other"
        different_root.mkdir()

        result = build_documentation(different_root)

        self.assertFalse(result["ok"])
        self.assertIn(
            "active VEGA project root",
            result["error"],
        )

    @patch("tools.doc_builders.build_documentation")
    def test_docgen_build_command_output(
        self,
        build_documentation_mock,
    ):
        build_documentation_mock.return_value = {
            "ok": True,
            "error": None,
            "data": {
                "passed": True,
                "version": "v1.9.0",
                "created_count": 1,
                "skipped_count": 0,
                "error_count": 0,
                "created": [
                    {
                        "document_id": "commands",
                        "path": "docs/commands.md",
                        "patch_id": "patch-commands",
                        "status": "pending",
                    },
                ],
                "skipped": [],
                "errors": [],
                "applied_automatically": False,
            },
        }

        output = handle_docgen_command(
            "/docgen build",
            self.root,
        )

        self.assertIn(
            "Documentation build",
            output,
        )
        self.assertIn(
            "Status: PASS",
            output,
        )
        self.assertIn(
            "Pending patches created: 1",
            output,
        )
        self.assertIn(
            "Automatic apply: NO",
            output,
        )
        self.assertIn(
            "patch-commands",
            output,
        )

        build_documentation_mock.assert_called_once_with(
            self.root
        )

    @patch("tools.doc_builders.build_documentation")
    def test_docgen_build_error_is_controlled(
        self,
        build_documentation_mock,
    ):
        build_documentation_mock.return_value = {
            "ok": False,
            "error": "Build policy could not be loaded.",
            "data": None,
        }

        output = handle_docgen_command(
            "/docgen build",
            self.root,
        )

        self.assertIn(
            "Documentation command error",
            output,
        )
        self.assertIn(
            "Build policy could not be loaded",
            output,
        )


if __name__ == "__main__":
    unittest.main()
