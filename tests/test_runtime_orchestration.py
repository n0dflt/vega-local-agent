import tempfile
import shutil
import unittest
from pathlib import Path

from core.agent_modes import (
    ModeRegistry,
    ModeSession,
)
from core.agent_runtime import (
    build_orchestrator,
)
from core.command_router import CommandTarget
from core.orchestrator import (
    AgentOrchestrator,
    OrchestrationKind,
)


class RuntimeOrchestrationTests(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )
        self.addCleanup(
            self.temporary_directory.cleanup
        )

        self.root = Path(
            self.temporary_directory.name
        ).resolve()
        (self.root / "config").mkdir()
        shutil.copy(
            Path(__file__).parents[1] / "config" / "checkpoint_policy.json",
            self.root / "config" / "checkpoint_policy.json",
        )

        self.mode_session = ModeSession(
            ModeRegistry()
        )

    def test_runtime_builds_orchestrator(
        self,
    ) -> None:
        orchestrator = build_orchestrator(
            root=self.root,
            model="test-model",
            log_file=Path("logs/test.log"),
            system_prompt="System prompt",
            mode_session=self.mode_session,
        )

        self.assertIsInstance(
            orchestrator,
            AgentOrchestrator,
        )
        self.assertEqual(
            orchestrator.context.model,
            "test-model",
        )
        self.assertEqual(
            orchestrator.context.project_root,
            self.root,
        )

    def test_runtime_orchestrator_routes_docs(
        self,
    ) -> None:
        orchestrator = build_orchestrator(
            root=self.root,
            model="test-model",
            log_file=Path("logs/test.log"),
            system_prompt="System prompt",
            mode_session=self.mode_session,
        )

        result = orchestrator.process(
            "/docs search architecture"
        )

        self.assertEqual(
            result.kind,
            OrchestrationKind.COMMAND,
        )
        self.assertEqual(
            result.command_route.target,
            CommandTarget.DOCS,
        )


if __name__ == "__main__":
    unittest.main()
