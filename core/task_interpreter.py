from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Tuple

from core.intent_analyzer import (
    IntentAnalysis,
    IntentType,
    normalize_request,
)


class TaskInterpretationError(ValueError):
    """Raised when a request cannot be safely interpreted."""


class OutputFormat(str, Enum):
    UNSPECIFIED = "unspecified"
    SUMMARY = "summary"
    REPORT = "report"
    LIST = "list"
    JSON = "json"
    TEXT = "text"


@dataclass(frozen=True)
class TaskInterpretation:
    """Structured parameters extracted from a user request."""

    intent: IntentType
    original_text: str
    source_path: str | None = None
    search_query: str | None = None
    workspace: str = "current_workspace"
    run_tests: bool = False
    run_compileall: bool = False
    allow_file_changes: bool = True
    allow_dependency_installation: bool = True
    allow_network: bool = True
    report_required: bool = False
    output_format: OutputFormat = OutputFormat.UNSPECIFIED
    constraints: Tuple[str, ...] = ()
    matched_values: Mapping[str, str] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        original_text = self.original_text.strip()
        source_path = (
            self.source_path.strip()
            if self.source_path is not None
            else None
        )
        search_query = (
            self.search_query.strip()
            if self.search_query is not None
            else None
        )
        constraints = tuple(
            dict.fromkeys(
                constraint.strip().lower()
                for constraint in self.constraints
                if constraint.strip()
            )
        )

        output_format = self.output_format
        if not isinstance(output_format, OutputFormat):
            output_format = OutputFormat(str(output_format))

        object.__setattr__(self, "original_text", original_text)
        object.__setattr__(self, "source_path", source_path)
        object.__setattr__(self, "search_query", search_query)
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "output_format", output_format)
        object.__setattr__(
            self,
            "matched_values",
            dict(self.matched_values),
        )

        if not original_text:
            raise TaskInterpretationError(
                "original_text must not be empty"
            )

        if not self.workspace.strip():
            raise TaskInterpretationError(
                "workspace must not be empty"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent.value,
            "original_text": self.original_text,
            "source_path": self.source_path,
            "search_query": self.search_query,
            "workspace": self.workspace,
            "run_tests": self.run_tests,
            "run_compileall": self.run_compileall,
            "allow_file_changes": self.allow_file_changes,
            "allow_dependency_installation": (
                self.allow_dependency_installation
            ),
            "allow_network": self.allow_network,
            "report_required": self.report_required,
            "output_format": self.output_format.value,
            "constraints": list(self.constraints),
            "matched_values": dict(self.matched_values),
        }


_QUOTED_VALUE_PATTERN = re.compile(
    r'"([^"]+)"|«([^»]+)»|“([^”]+)”'
)

_PATH_PATTERN = re.compile(
    r"(?P<path>"
    r"(?:[A-Za-z]:[\\/]|\.{1,2}[\\/])?"
    r"[^\s\"«»]+?"
    r"\.(?:pdf|txt|md|py|json|ya?ml|toml|csv|docx)"
    r")\b",
    flags=re.IGNORECASE,
)

_SUPPORTED_FILE_SUFFIXES = (
    ".pdf",
    ".txt",
    ".md",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".docx",
)


def _quoted_values(text: str) -> Tuple[str, ...]:
    values: list[str] = []

    for match in _QUOTED_VALUE_PATTERN.finditer(text):
        value = next(
            group
            for group in match.groups()
            if group is not None
        ).strip()

        if value:
            values.append(value)

    return tuple(values)


def _looks_like_file_path(value: str) -> bool:
    normalized = value.strip().lower().rstrip(".,;:!?")
    return normalized.endswith(_SUPPORTED_FILE_SUFFIXES)


def _extract_source_path(text: str) -> str | None:
    for value in _quoted_values(text):
        if _looks_like_file_path(value):
            return value

    match = _PATH_PATTERN.search(text)

    if match is None:
        return None

    return match.group("path").rstrip(".,;:!?")


def _clean_search_query(value: str) -> str | None:
    cleaned = value.strip(" \t\r\n.,;:!?")

    cleaned = re.sub(
        r"\s+(?:в проекте|в файлах|по проекту)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s+(?:in the project|in project|in files)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    return cleaned.strip() or None


def _extract_search_query(
    text: str,
    source_path: str | None,
) -> str | None:
    for value in _quoted_values(text):
        if source_path is None or value != source_path:
            return _clean_search_query(value)

    normalized = normalize_request(text)

    patterns = (
        re.compile(
            r"\b(?:найди|поищи|отыщи)\s+"
            r"(?:(?:в проекте|в файлах)\s+)?"
            r"(?P<query>.+)$"
        ),
        re.compile(
            r"\b(?:find|search(?:\s+for)?)\s+"
            r"(?:(?:in\s+(?:the\s+)?project)\s+)?"
            r"(?P<query>.+)$"
        ),
    )

    for pattern in patterns:
        match = pattern.search(normalized)

        if match is not None:
            return _clean_search_query(
                match.group("query")
            )

    return None


def _detect_output_format(text: str) -> OutputFormat:
    normalized = normalize_request(text)

    if re.search(r"\bjson\b", normalized):
        return OutputFormat.JSON

    if re.search(
        r"\b(?:отчет\w*|report)\b",
        normalized,
    ):
        return OutputFormat.REPORT

    if re.search(
        r"\b(?:резюме|сводк\w*|summary|summar\w*)\b",
        normalized,
    ):
        return OutputFormat.SUMMARY

    if re.search(
        r"\b(?:список|перечень|list)\b",
        normalized,
    ):
        return OutputFormat.LIST

    if re.search(
        r"\b(?:текст\w*|plain text)\b",
        normalized,
    ):
        return OutputFormat.TEXT

    return OutputFormat.UNSPECIFIED


def _extract_constraints(text: str) -> Tuple[str, ...]:
    normalized = normalize_request(text)
    constraints: list[str] = []

    if re.search(
        r"\b(?:кратк\w*|коротк\w*|brief|concise)\b",
        normalized,
    ):
        constraints.append("brief")

    if re.search(
        r"(?:не изменяй|без изменений|"
        r"только проанализируй|read[- ]?only)",
        normalized,
    ):
        constraints.append("read_only")

    if re.search(
        r"(?:не устанавливай зависимост\w*|без установк\w+ зависимост\w*|"
        r"do not install dependenc\w*|without installing dependenc\w*)",
        normalized,
    ):
        constraints.append("no_dependency_installation")

    if re.search(
        r"(?:не используй сеть|без сетев\w+ действ\w*|"
        r"do not use (?:the )?network|without network(?: access| actions)?)",
        normalized,
    ):
        constraints.append("no_network")

    if re.search(
        r"\b(?:только staged|staged only|индексированн\w*)\b",
        normalized,
    ):
        constraints.append("staged_only")

    return tuple(constraints)


def interpret_task(
    analysis: IntentAnalysis,
) -> TaskInterpretation:
    """Extract task parameters without executing tools."""

    if not isinstance(analysis, IntentAnalysis):
        raise TypeError(
            "analysis must be an IntentAnalysis instance"
        )

    if not analysis.is_actionable:
        raise TaskInterpretationError(
            "cannot interpret an unknown intent"
        )

    source_path = _extract_source_path(
        analysis.original_text
    )

    search_query = None
    if analysis.intent in {
        IntentType.PROJECT_SEARCH,
        IntentType.BUG_FIX,
    }:
        search_query = _extract_search_query(
            analysis.original_text,
            source_path,
        )
        if (
            search_query is None
            and analysis.intent is IntentType.BUG_FIX
        ):
            search_query = analysis.normalized_text

    output_format = _detect_output_format(
        analysis.original_text
    )
    constraints = _extract_constraints(
        analysis.original_text
    )

    run_tests = bool(re.search(
        r"\b(?:pytest|тест\w*|tests?|test suite)\b",
        analysis.normalized_text,
    ))
    run_compileall = bool(re.search(
        r"\b(?:compileall|compile[- ]?check|компиляц\w*)\b",
        analysis.normalized_text,
    ))
    if analysis.intent is IntentType.WORKSPACE_DIAGNOSTICS:
        # A general workspace diagnostic is a bounded validation workflow.
        run_tests = True
        run_compileall = True

    read_only = "read_only" in constraints
    no_dependencies = "no_dependency_installation" in constraints
    no_network = "no_network" in constraints
    workspace_diagnostics = (
        analysis.intent is IntentType.WORKSPACE_DIAGNOSTICS
    )
    report_required = workspace_diagnostics or (
        output_format in {OutputFormat.REPORT, OutputFormat.SUMMARY}
    )

    matched_values: dict[str, str] = {}

    if source_path is not None:
        matched_values["source_path"] = source_path

    if search_query is not None:
        matched_values["search_query"] = search_query

    if output_format is not OutputFormat.UNSPECIFIED:
        matched_values["output_format"] = (
            output_format.value
        )

    return TaskInterpretation(
        intent=analysis.intent,
        original_text=analysis.original_text,
        source_path=source_path,
        search_query=search_query,
        workspace="current_workspace",
        run_tests=run_tests,
        run_compileall=run_compileall,
        allow_file_changes=not (read_only or workspace_diagnostics),
        allow_dependency_installation=not (
            no_dependencies or workspace_diagnostics
        ),
        allow_network=not (no_network or workspace_diagnostics),
        report_required=report_required,
        output_format=output_format,
        constraints=constraints,
        matched_values=matched_values,
    )
