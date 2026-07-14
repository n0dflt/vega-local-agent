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


def test_document_analysis_without_source_is_rejected() -> None:
    analysis = analyze_intent(
        "\u041f\u0440\u043e\u0430\u043d\u0430"
        "\u043b\u0438\u0437\u0438\u0440\u0443\u0439 "
        "\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442 "
        "\u0438 "
        "\u0441\u0434\u0435\u043b\u0430\u0439 "
        "\u043a\u0440\u0430\u0442\u043a\u0438\u0439 "
        "\u043e\u0442\u0447\u0451\u0442"
    )

    with pytest.raises(
        ToolPlanningError,
        match="source path is required",
    ):
        plan_tools(analysis, _tool_catalog())


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


def test_code_review_uses_safe_git_diff_tool() -> None:
    analysis = analyze_intent(
        "Посмотри изменения и оцени риски"
    )

    catalog = (
        ToolDescriptor(
            name="git.show_diff",
            permission="READ",
            capabilities=("git.diff",),
        ),
    )

    plan = plan_tools(analysis, catalog)

    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "git.show_diff"
    assert plan.steps[0].required_permission == "READ"


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
    assert plan.steps[0].arguments == {
        "group_id": "all",
        "project_root": ".",
    }
