from core.intent_analyzer import IntentType
from domains.builtin import build_builtin_domain_registry
from tools.registry import BUILTIN_TOOL_REGISTRY


def test_builtin_domains_cover_current_intents_and_real_tools():
    first = build_builtin_domain_registry()
    second = build_builtin_domain_registry()
    assert first is not second
    assert tuple(item.name for item in first.list_domains()) == ("coding", "research")
    assert {intent.value for intent in IntentType if intent is not IntentType.UNKNOWN} <= {
        intent for domain in first.list_domains() for intent in domain.intents
    }
    assert all(
        name in BUILTIN_TOOL_REGISTRY
        for domain in first.list_domains()
        for name in domain.tool_names
    )
    assert "web_fetch" not in first.require("research").tool_names
