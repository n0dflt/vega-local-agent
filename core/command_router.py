"""Deterministic slash-command routing for VEGA."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from core.intent_router import IntentKind, RoutedIntent


class CommandTarget(str, Enum):
    """Supported command-handler groups."""

    ABOUT = "about"
    HELP = "help"
    STATUS = "status"
    DOCTOR = "doctor"
    DOCS = "docs"
    WORKSPACE = "workspace"
    MODEL = "model"
    PROJECT = "project"
    CLEAR = "clear"
    LOG = "log"
    TASK = "task"
    JOURNAL = "journal"
    FILE = "file"
    PATCH = "patch"
    GIT = "git"
    TOOLS = "tools"
    MEMORY = "memory"
    TERMINAL = "terminal"
    TEST = "test"
    INTERNET = "internet"
    WEB = "web"
    MODE = "mode"
    DOCGEN = "docgen"
    RELEASE = "release"
    WORKFLOW = "workflow"
    EXIT = "exit"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CommandRoute:
    """Describe the handler selected for one slash command."""

    target: CommandTarget
    command_name: str
    command_arguments: str
    normalized_command: str

    @property
    def is_known(self) -> bool:
        """Return whether the command has a registered target."""
        return self.target is not CommandTarget.UNKNOWN

    @property
    def is_exit(self) -> bool:
        """Return whether the command should stop the runtime."""
        return self.target is CommandTarget.EXIT


_DEFAULT_ROUTES = MappingProxyType(
    {
        "/about": CommandTarget.ABOUT,
        "/help": CommandTarget.HELP,
        "/status": CommandTarget.STATUS,
        "/doctor": CommandTarget.DOCTOR,
        "/docs": CommandTarget.DOCS,
        "/workspace": CommandTarget.WORKSPACE,
        "/model": CommandTarget.MODEL,
        "/project": CommandTarget.PROJECT,
        "/clear": CommandTarget.CLEAR,
        "/log": CommandTarget.LOG,
        "/task": CommandTarget.TASK,
        "/journal": CommandTarget.JOURNAL,
        "/file": CommandTarget.FILE,
        "/patch": CommandTarget.PATCH,
        "/git": CommandTarget.GIT,
        "/tools": CommandTarget.TOOLS,
        "/memory": CommandTarget.MEMORY,
        "/run": CommandTarget.TERMINAL,
        "/test": CommandTarget.TEST,
        "/internet": CommandTarget.INTERNET,
        "/web": CommandTarget.WEB,
        "/mode": CommandTarget.MODE,
        "/docgen": CommandTarget.DOCGEN,
        "/release": CommandTarget.RELEASE,
        "/workflow": CommandTarget.WORKFLOW,
        "/exit": CommandTarget.EXIT,
        "/bye": CommandTarget.EXIT,
        "/q": CommandTarget.EXIT,
    }
)


class CommandRouter:
    """Map a routed slash command to a deterministic handler group."""

    def __init__(
        self,
        routes: Mapping[str, CommandTarget] | None = None,
    ) -> None:
        configured_routes = dict(_DEFAULT_ROUTES)

        if routes is not None:
            configured_routes.update(
                self._validate_routes(routes)
            )

        self._routes = MappingProxyType(
            configured_routes
        )

    def route(
        self,
        intent: RoutedIntent,
    ) -> CommandRoute:
        """Return routing metadata for one command intent."""
        if not isinstance(intent, RoutedIntent):
            raise TypeError(
                "intent must be a RoutedIntent instance."
            )

        if intent.kind is not IntentKind.COMMAND:
            raise ValueError(
                "CommandRouter accepts only command intents."
            )

        command_name = intent.command_name

        if not command_name:
            raise ValueError(
                "Command intent does not contain a command name."
            )

        arguments = intent.command_arguments.strip()
        normalized_command = command_name

        if arguments:
            normalized_command = (
                f"{command_name} {arguments}"
            )

        return CommandRoute(
            target=self._routes.get(
                command_name,
                CommandTarget.UNKNOWN,
            ),
            command_name=command_name,
            command_arguments=arguments,
            normalized_command=normalized_command,
        )

    def registered_commands(self) -> tuple[str, ...]:
        """Return all registered command names in sorted order."""
        return tuple(
            sorted(self._routes)
        )

    @staticmethod
    def _validate_routes(
        routes: Mapping[str, CommandTarget],
    ) -> dict[str, CommandTarget]:
        if not isinstance(routes, Mapping):
            raise TypeError(
                "routes must implement the Mapping interface."
            )

        validated: dict[str, CommandTarget] = {}

        for command_name, target in routes.items():
            if not isinstance(command_name, str):
                raise TypeError(
                    "Command route names must be strings."
                )

            normalized_name = command_name.strip().lower()

            if (
                not normalized_name.startswith("/")
                or " " in normalized_name
                or len(normalized_name) == 1
            ):
                raise ValueError(
                    f"Invalid command route name: "
                    f"{command_name!r}."
                )

            if not isinstance(target, CommandTarget):
                raise TypeError(
                    f"Route target for {normalized_name!r} "
                    "must be a CommandTarget value."
                )

            validated[normalized_name] = target

        return validated
