import unittest

from core.command_router import (
    CommandRouter,
    CommandTarget,
)
from core.intent_router import IntentRouter


class CommandRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intent_router = IntentRouter()
        self.command_router = CommandRouter()

    def route_command(self, command: str):
        intent = self.intent_router.route(command)
        return self.command_router.route(intent)

    def test_status_command_routes_to_status(self) -> None:
        route = self.route_command("/status")

        self.assertEqual(
            route.target,
            CommandTarget.STATUS,
        )
        self.assertTrue(route.is_known)
        self.assertFalse(route.is_exit)

    def test_command_name_is_normalized(self) -> None:
        route = self.route_command("/STATUS")

        self.assertEqual(
            route.command_name,
            "/status",
        )
        self.assertEqual(
            route.target,
            CommandTarget.STATUS,
        )

    def test_command_arguments_are_preserved(self) -> None:
        route = self.route_command(
            "/task new   Add orchestrator"
        )

        self.assertEqual(
            route.target,
            CommandTarget.TASK,
        )
        self.assertEqual(
            route.command_arguments,
            "new   Add orchestrator",
        )
        self.assertEqual(
            route.normalized_command,
            "/task new   Add orchestrator",
        )

    def test_command_without_arguments_is_normalized(self) -> None:
        route = self.route_command("/help")

        self.assertEqual(
            route.normalized_command,
            "/help",
        )
        self.assertEqual(
            route.command_arguments,
            "",
        )

    def test_exit_aliases_route_to_exit(self) -> None:
        for command in (
            "/exit",
            "/bye",
            "/q",
        ):
            with self.subTest(command=command):
                route = self.route_command(command)

                self.assertEqual(
                    route.target,
                    CommandTarget.EXIT,
                )
                self.assertTrue(route.is_exit)
                self.assertTrue(route.is_known)

    def test_unknown_command_routes_to_unknown(self) -> None:
        route = self.route_command(
            "/unknown"
        )

        self.assertEqual(
            route.target,
            CommandTarget.UNKNOWN,
        )
        self.assertFalse(route.is_known)
        self.assertFalse(route.is_exit)


    def test_docs_command_routes_to_docs(self) -> None:
        route = self.route_command(
            "/docs search architecture"
        )

        self.assertEqual(
            route.target,
            CommandTarget.DOCS,
        )
        self.assertEqual(
            route.command_arguments,
            "search architecture",
        )

    def test_all_current_command_groups_are_registered(self) -> None:
        expected_commands = {
            "/about",
            "/help",
            "/status",
            "/doctor",
            "/docs",
            "/workspace",
            "/model",
            "/project",
            "/clear",
            "/log",
            "/task",
            "/journal",
            "/file",
            "/patch",
            "/git",
            "/tools",
            "/memory",
            "/run",
            "/test",
            "/internet",
            "/web",
            "/mode",
            "/docgen",
            "/release",
            "/workflow",
            "/exit",
            "/bye",
            "/q",
        }

        self.assertEqual(
            set(
                self.command_router.registered_commands()
            ),
            expected_commands,
        )

    def test_registered_commands_are_sorted(self) -> None:
        commands = (
            self.command_router.registered_commands()
        )

        self.assertEqual(
            commands,
            tuple(sorted(commands)),
        )

    def test_custom_route_can_override_default_route(self) -> None:
        router = CommandRouter(
            {
                "/status": CommandTarget.DOCTOR,
            }
        )

        intent = self.intent_router.route(
            "/status"
        )
        route = router.route(intent)

        self.assertEqual(
            route.target,
            CommandTarget.DOCTOR,
        )

    def test_custom_route_name_is_normalized(self) -> None:
        router = CommandRouter(
            {
                " /CUSTOM ": CommandTarget.STATUS,
            }
        )

        intent = self.intent_router.route(
            "/custom"
        )
        route = router.route(intent)

        self.assertEqual(
            route.target,
            CommandTarget.STATUS,
        )

    def test_invalid_custom_route_name_is_rejected(self) -> None:
        invalid_names = (
            "",
            "/",
            "status",
            "/invalid route",
        )

        for name in invalid_names:
            with self.subTest(name=name):
                with self.assertRaises(
                    ValueError
                ):
                    CommandRouter(
                        {
                            name: CommandTarget.STATUS,
                        }
                    )

    def test_invalid_custom_route_target_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            CommandRouter(
                {
                    "/custom": "status",
                }
            )

    def test_non_command_intent_is_rejected(self) -> None:
        intent = self.intent_router.route(
            "Regular chat message"
        )

        with self.assertRaises(ValueError):
            self.command_router.route(intent)

    def test_invalid_intent_type_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            self.command_router.route(
                "/status"
            )


if __name__ == "__main__":
    unittest.main()
