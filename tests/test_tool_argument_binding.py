import pytest

from core.intent_analyzer import analyze_intent
from core.task_interpreter import interpret_task
from core.tool_planner import (
    ToolDescriptor,
    ToolPlanningError,
    plan_tools,
)


def _safe_catalog() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            name="read_file",
            permission="READ",
            capabilities=("document.read",),
        ),
        ToolDescriptor(
            name="summarize_file",
            permission="READ",
            capabilities=("document.summarize",),
        ),
        ToolDescriptor(
            name="search_in_files",
            permission="READ",
            capabilities=("project.search",),
        ),
        ToolDescriptor(
            name="git_diff",
            permission="READ",
            capabilities=("git.diff",),
        ),
        ToolDescriptor(
            name="git_diff_cached",
            permission="READ",
            capabilities=("git.diff.cached",),
        ),
        ToolDescriptor(
            name="documentation_status",
            permission="READ",
            capabilities=("documentation.status",),
        ),
        ToolDescriptor(
            name="release_status",
            permission="READ",
            capabilities=("release.status",),
        ),
    )


def test_document_path_is_bound_to_summary_tool() -> None:
    analysis = analyze_intent(
        '????????????? "docs/report.pdf" '
        "? ?????? ??????? ?????"
    )
    interpretation = interpret_task(analysis)

    plan = plan_tools(
        analysis,
        _safe_catalog(),
        interpretation=interpretation,
        workspace="C:/project",
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "summarize_file"
    assert plan.steps[0].arguments == {
        "path": "docs/report.pdf",
    }


def test_project_search_query_uses_safe_relative_path() -> None:
    analysis = analyze_intent(
        'Найди "legacy_client" в проекте'
    )
    interpretation = interpret_task(analysis)

    plan = plan_tools(
        analysis,
        _safe_catalog(),
        interpretation=interpretation,
        workspace="C:/project",
    )

    assert plan.steps[0].tool_name == "search_in_files"
    assert plan.steps[0].arguments == {
        "query": "legacy_client",
        "path": ".",
    }


def test_staged_review_uses_cached_diff() -> None:
    analysis = analyze_intent(
        "Посмотри только staged изменения "
        "и оцени риски"
    )
    interpretation = interpret_task(analysis)

    plan = plan_tools(
        analysis,
        _safe_catalog(),
        interpretation=interpretation,
        workspace="C:/project",
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "git_diff_cached"
    assert plan.steps[0].arguments == {
        "workspace": "C:/project",
    }


def test_documentation_update_uses_safe_preview() -> None:
    analysis = analyze_intent(
        "Обнови документацию после изменений"
    )
    interpretation = interpret_task(analysis)

    plan = plan_tools(
        analysis,
        _safe_catalog(),
        interpretation=interpretation,
        workspace="C:/project",
    )

    assert tuple(
        step.tool_name
        for step in plan.steps
    ) == (
        "git_diff",
        "documentation_status",
    )

    assert plan.steps[0].arguments == {
        "workspace": "C:/project",
    }
    assert plan.steps[1].arguments == {
        "project_root": "C:/project",
    }
    assert plan.steps[1].depends_on == (1,)


def test_release_status_receives_project_root() -> None:
    analysis = analyze_intent(
        "Проверь, готов ли проект к релизу"
    )
    interpretation = interpret_task(analysis)

    plan = plan_tools(
        analysis,
        _safe_catalog(),
        interpretation=interpretation,
        workspace="C:/project",
    )

    assert plan.steps[0].tool_name == "release_status"
    assert plan.steps[0].arguments == {
        "project_root": "C:/project",
    }


def test_document_analysis_without_path_fails_closed() -> None:
    analysis = analyze_intent(
        "Проанализируй документ "
        "и сделай краткий отчёт"
    )
    interpretation = interpret_task(analysis)

    with pytest.raises(
        ToolPlanningError,
        match="source path is required",
    ):
        plan_tools(
            analysis,
            _safe_catalog(),
            interpretation=interpretation,
        )
