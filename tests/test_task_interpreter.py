import pytest

from core.intent_analyzer import analyze_intent
from core.task_interpreter import (
    OutputFormat,
    TaskInterpretationError,
    interpret_task,
)


def test_document_request_extracts_quoted_path() -> None:
    analysis = analyze_intent(
        'Проанализируй "docs/report.pdf" '
        "и сделай краткий отчёт"
    )

    result = interpret_task(analysis)

    assert result.source_path == "docs/report.pdf"
    assert result.output_format is OutputFormat.REPORT
    assert "brief" in result.constraints


def test_document_request_extracts_relative_path() -> None:
    analysis = analyze_intent(
        "Сделай резюме файла ./docs/architecture.md"
    )

    result = interpret_task(analysis)

    assert result.source_path == "./docs/architecture.md"
    assert result.output_format is OutputFormat.SUMMARY


def test_project_search_extracts_natural_query() -> None:
    analysis = analyze_intent(
        "Найди в проекте использование старого API"
    )

    result = interpret_task(analysis)

    assert result.search_query == (
        "использование старого api"
    )


def test_project_search_prefers_quoted_query() -> None:
    analysis = analyze_intent(
        'Найди "legacy_client" в проекте'
    )

    result = interpret_task(analysis)

    assert result.search_query == "legacy_client"


def test_read_only_constraint_is_detected() -> None:
    analysis = analyze_intent(
        "Проанализируй файл config.json, "
        "но не изменяй проект"
    )

    result = interpret_task(analysis)

    assert result.source_path == "config.json"
    assert "read_only" in result.constraints


def test_json_output_format_is_detected() -> None:
    analysis = analyze_intent(
        "Проанализируй document.md "
        "и верни результат в JSON"
    )

    result = interpret_task(analysis)

    assert result.output_format is OutputFormat.JSON


def test_result_serializes() -> None:
    analysis = analyze_intent(
        'Найди "old_api" в проекте'
    )

    result = interpret_task(analysis).to_dict()

    assert result["intent"] == "project_search"
    assert result["search_query"] == "old_api"
    assert result["matched_values"]["search_query"] == (
        "old_api"
    )


def test_unknown_intent_is_rejected() -> None:
    analysis = analyze_intent(
        "Расскажи что-нибудь интересное"
    )

    with pytest.raises(
        TaskInterpretationError,
        match="unknown intent",
    ):
        interpret_task(analysis)


def test_invalid_analysis_type_is_rejected() -> None:
    with pytest.raises(
        TypeError,
        match="IntentAnalysis",
    ):
        interpret_task(None)  # type: ignore[arg-type]


def test_workspace_diagnostics_preserves_machine_constraints() -> None:
    analysis = analyze_intent(
        "Проведи безопасную диагностику текущего проекта. Не изменяй "
        "файлы, не устанавливай зависимости и не используй сеть. "
        "Запусти pytest и python -m compileall, затем сделай отчёт."
    )

    result = interpret_task(analysis)

    assert result.workspace == "current_workspace"
    assert result.run_tests is True
    assert result.run_compileall is True
    assert result.allow_file_changes is False
    assert result.allow_dependency_installation is False
    assert result.allow_network is False
    assert result.report_required is True
    assert set(result.constraints) >= {
        "read_only",
        "no_dependency_installation",
        "no_network",
    }
