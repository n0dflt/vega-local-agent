import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

from core.agent_modes import ModeRegistry, ModeSession
from core.agent_runtime import build_command_executor
from core.command_executor import (
    CommandExecutionRequest,
    CommandExecutionStatus,
    CommandExecutor,
)
from core.command_router import CommandRoute, CommandTarget
from core.execution_context import ExecutionContext
from core.tool_executor import ToolExecutor


def make_route(
    target: CommandTarget,
    command_name: str,
    arguments: str = "",
) -> CommandRoute:
    normalized_command = command_name
    if arguments:
        normalized_command = f"{command_name} {arguments}"

    return CommandRoute(
        target=target,
        command_name=command_name,
        command_arguments=arguments,
        normalized_command=normalized_command,
    )


class RuntimeCommandExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name).resolve()
        self.mode_session = ModeSession(ModeRegistry())
        self.log_file = self.root / "session.log"
        self.context = ExecutionContext(
            project_root=self.root,
            model="test-model",
            log_file=self.log_file,
            system_prompt="System prompt",
            mode_session=self.mode_session,
        )

    def execute(
        self,
        target: CommandTarget,
        command_name: str,
        arguments: str = "",
        tool_executor: ToolExecutor | None = None,
    ):
        executor = build_command_executor(
            self.context,
            tool_executor=tool_executor,
        )
        route = make_route(target, command_name, arguments)
        return executor.execute(CommandExecutionRequest(route))

    def test_factory_returns_command_executor(self) -> None:
        self.assertIsInstance(
            build_command_executor(self.context),
            CommandExecutor,
        )

    def test_factory_rejects_invalid_context(self) -> None:
        with self.assertRaises(TypeError):
            build_command_executor(object())

    def test_registry_contains_all_known_targets(self) -> None:
        targets = build_command_executor(
            self.context
        ).registered_targets()

        self.assertEqual(
            set(targets),
            set(CommandTarget) - {CommandTarget.UNKNOWN},
        )

    def test_unknown_target_is_not_registered(self) -> None:
        targets = build_command_executor(
            self.context
        ).registered_targets()

        self.assertNotIn(CommandTarget.UNKNOWN, targets)

    @patch("core.agent_runtime.handle_command")
    def test_legacy_adapter_calls_existing_handler(self, handler) -> None:
        handler.return_value = True

        result = self.execute(
            CommandTarget.STATUS,
            "/status",
        )

        self.assertTrue(result.ok)
        handler.assert_called_once_with(
            "/status",
            self.context.project_root,
            self.context.log_file,
            self.context.model,
            self.context.mode_session,
            tool_executor=ANY,
        )

    @patch("core.agent_runtime.handle_command")
    def test_factory_passes_injected_tool_executor(self, handler) -> None:
        handler.return_value = True
        tool_executor = ToolExecutor({})

        self.execute(
            CommandTarget.STATUS,
            "/status",
            tool_executor=tool_executor,
        )

        self.assertIs(
            handler.call_args.kwargs["tool_executor"],
            tool_executor,
        )

    def test_factory_rejects_invalid_tool_executor(self) -> None:
        with self.assertRaises(TypeError):
            build_command_executor(
                self.context,
                tool_executor=object(),
            )

    @patch("core.agent_runtime.dispatch_docs_command")
    @patch("core.agent_runtime.handle_command")
    def test_docs_uses_only_docs_adapter(
        self,
        legacy_handler,
        docs_handler,
    ) -> None:
        tool_calls = []
        tool_executor = ToolExecutor(
            {"sentinel": lambda: tool_calls.append(True)}
        )
        result = self.execute(
            CommandTarget.DOCS,
            "/docs",
            "search architecture",
            tool_executor=tool_executor,
        )

        self.assertTrue(result.ok)
        docs_handler.assert_called_once_with(
            "/docs search architecture",
            self.context.project_root,
        )
        legacy_handler.assert_not_called()
        self.assertEqual(tool_calls, [])

    @patch("core.agent_runtime.dispatch_docs_command")
    def test_docs_is_logged_once(self, docs_handler) -> None:
        self.execute(CommandTarget.DOCS, "/docs", "list")

        log_text = self.log_file.read_text(encoding="utf-8")
        self.assertEqual(log_text.count("[COMMAND]"), 1)
        self.assertEqual(log_text.count("/docs list"), 1)

    @patch("core.agent_runtime.append_log")
    @patch("core.agent_runtime.handle_command")
    def test_legacy_adapter_does_not_add_logging(
        self,
        handler,
        append_log,
    ) -> None:
        handler.return_value = True

        self.execute(CommandTarget.STATUS, "/status")

        append_log.assert_not_called()

    @patch("core.agent_runtime.handle_command")
    def test_exit_returns_keep_running_false(self, handler) -> None:
        handler.return_value = False

        result = self.execute(CommandTarget.EXIT, "/exit")

        self.assertTrue(result.ok)
        self.assertFalse(result.keep_running)
        handler.assert_called_once()

    @patch("core.agent_runtime.handle_command")
    def test_legacy_exception_returns_failed(self, handler) -> None:
        handler.side_effect = RuntimeError("legacy failure")

        result = self.execute(CommandTarget.STATUS, "/status")

        self.assertEqual(
            result.status,
            CommandExecutionStatus.FAILED,
        )
        self.assertIn("RuntimeError", result.error)

    @patch("rag.commands.handle_docs_command")
    def test_docs_exception_returns_failed(self, docs_handler) -> None:
        docs_handler.side_effect = ValueError("docs failure")

        result = self.execute(CommandTarget.DOCS, "/docs")

        self.assertEqual(
            result.status,
            CommandExecutionStatus.FAILED,
        )
        self.assertIn("ValueError", result.error)
        self.assertFalse(self.log_file.exists())

    def test_unknown_command_returns_unknown_status(self) -> None:
        result = self.execute(
            CommandTarget.UNKNOWN,
            "/unknown",
        )

        self.assertEqual(
            result.status,
            CommandExecutionStatus.UNKNOWN_COMMAND,
        )

    @patch("core.agent_runtime.handle_command")
    def test_handler_error_does_not_exit_process(self, handler) -> None:
        handler.side_effect = RuntimeError("exit failure")

        result = self.execute(CommandTarget.EXIT, "/exit")

        self.assertEqual(
            result.status,
            CommandExecutionStatus.FAILED,
        )
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
