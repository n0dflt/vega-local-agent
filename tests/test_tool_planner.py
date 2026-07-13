import pytest

from core.intent_analyzer import analyze_intent
from core.tool_planner import (
    ToolDescriptor,
    ToolPlanningError,
    plan_tools,
)


def _tool_catalog() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            name="files.search",
            permission="READ",
            capabilities=("project.search",),
        ),
        ToolDescriptor(
            name="documents.read",
            permission="READ",
            capabilities=("document.read",),
        ),
        ToolDescriptor(
            name="documents.summarize",
            permission="DRAFT",
            capabilities=("document.summarize",),
        ),
        ToolDescriptor(
            name="patches.propose",
            permission="DRAFT",
            capabilities=("patch.propose",),
        ),
        ToolDescriptor(
            name="tests.run",
            permission="EXECUTE",
            capabilities=("test.run",),
        ),
        ToolDescriptor(
            name="git.show_diff",
            permission="READ",
            capabilities=("git.diff",),
        ),
        ToolDescriptor(
            name="review.code",
            permission="DRAFT",
            capabilities=("code.review",),
        ),
        ToolDescriptor(
            name="docs.update",
            permission="WRITE",
            capabilities=("documentation.update",),
        ),
        ToolDescriptor(
            name="release.check",
            permission="READ",
            capabilities=("release.check",),
        ),
    )


def test_project_search_uses_available_registered_tool() -> None:
    analysis = analyze_intent(
        "Найди в проекте использование старого API"
    )

    plan = plan_tools(analysis, _tool_catalog())

    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "files.search"
    assert plan.steps[0].required_permission == "READ"
    assert plan.metadata["intent"] == "project_search"


def test_document_analysis_builds_ordered_plan() -> None:
    analysis = analyze_intent(
        "Проанализируй документ и сделай краткий отчёт"
    )

    plan = plan_tools(analysis, _tool_catalog())

    assert tuple(
        step.tool_name for step in plan.steps
    ) == (
        "documents.read",
        "documents.summarize",
    )
    assert plan.steps[0].depends_on == ()
    assert plan.steps[1].depends_on == (1,)
    assert plan.required_permissions() == (
        "READ",
        "DRAFT",
    )


def test_bug_fix_plan_preserves_permission_levels() -> None:
    analysis = analyze_intent(
        "Исправь ошибку и проверь тесты"
    )

    plan = plan_tools(analysis, _tool_catalog())

    assert tuple(
        step.tool_name for step in plan.steps
    ) == (
        "files.search",
        "patches.propose",
        "tests.run",
    )
    assert plan.required_permissions() == (
        "READ",
        "DRAFT",
        "EXECUTE",
    )
    assert plan.requires_confirmation(
        {"READ", "DRAFT"}
    ) is True


def test_planner_rejects_missing_capability() -> None:
    analysis = analyze_intent(
        "Посмотри изменения и оцени риски"
    )

    incomplete_catalog = (
        ToolDescriptor(
            name="git.show_diff",
            permission="READ",
            capabilities=("git.diff",),
        ),
    )

    with pytest.raises(
        ToolPlanningError,
        match="code.review",
    ):
        plan_tools(analysis, incomplete_catalog)


def test_planner_rejects_unknown_intent() -> None:
    analysis = analyze_intent(
        "Расскажи что-нибудь интересное"
    )

    with pytest.raises(
        ToolPlanningError,
        match="unknown intent",
    ):
        plan_tools(analysis, _tool_catalog())


def test_planner_never_invents_tool_name() -> None:
    analysis = analyze_intent(
        "Запусти pytest"
    )

    custom_catalog = (
        ToolDescriptor(
            name="safe_test_executor",
            permission="EXECUTE",
            capabilities=("test.run",),
        ),
    )

    plan = plan_tools(analysis, custom_catalog)

    assert plan.steps[0].tool_name == "safe_test_executor"
    assert plan.steps[0].tool_name != "pytest"
    assert plan.steps[0].arguments == {}
