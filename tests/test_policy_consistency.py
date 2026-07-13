from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core.contextual_router import ToolRoutingPolicy
from core.model_selection import ModelRoutingPolicy
from core.policy_consistency import (
    PolicyConsistencyIssue,
    PolicyConsistencyReport,
    PolicyIssueCode,
    PolicyIssueSeverity,
    PolicyPermission,
    PolicyTool,
    validate_policy_consistency,
)
from domains.models import DomainDefinition
from plugins.models import PluginToolActivation, PluginToolState


def domain(
    *,
    name: str = "sample",
    intents=("alpha",),
    capabilities=("cap.read",),
    tool_names=("reader",),
    enabled: bool = True,
) -> DomainDefinition:
    return DomainDefinition(
        name=name,
        description="Test domain.",
        intents=intents,
        capabilities=capabilities,
        tool_names=tool_names,
        enabled=enabled,
    )


def model_policy(**changes) -> ModelRoutingPolicy:
    values = {
        "enabled": True,
        "fallback_profile": "code",
        "intent_profiles": {"alpha": "code", "unknown": "code"},
        "fallback_order": ("code",),
        "deep_request_chars": 100,
        "deep_signals": (),
        "context_budgets": {"code": 1000},
        "head_ratio": 0.5,
    }
    values.update(changes)
    return ModelRoutingPolicy(**values)


def base_values() -> dict:
    return {
        "intents": ("alpha", "unknown"),
        "intent_routes": {"alpha": ("cap.read",)},
        "domains": (domain(),),
        "tools": (
            PolicyTool(
                "reader",
                capabilities=("cap.read",),
                routing_permission="READ",
                contextual=True,
                routing_metadata=True,
            ),
        ),
        "permissions": (PolicyPermission("reader", "allow", "low"),),
        "routing_policy": ToolRoutingPolicy(
            enabled=True,
            allow_explicit_execution=True,
            automatic_permissions=("READ", "DRAFT"),
            confirmation_permissions=("WRITE", "EXECUTE"),
            max_tool_steps=8,
            allow_arbitrary_tool_names=False,
            allow_shell_generation=False,
            fail_closed=True,
        ),
        "model_policy": model_policy(),
        "known_model_profiles": ("code",),
        "plugin_activations": (),
        "plugin_policy_enabled": False,
    }


def validate(**changes) -> PolicyConsistencyReport:
    values = base_values()
    values.update(changes)
    return validate_policy_consistency(**values)


def codes(report: PolicyConsistencyReport) -> set[PolicyIssueCode]:
    return {issue.code for issue in report.issues}


def test_valid_builtin_metadata_has_no_issues() -> None:
    report = validate()
    assert report.ok
    assert report.can_execute_tools
    assert report.issues == ()
    assert report.summary == "fatal=0; degraded=0; warning=0"


def test_issue_and_report_are_immutable_and_deterministic() -> None:
    first = PolicyConsistencyIssue(
        PolicyIssueCode.TOOL_MISSING,
        PolicyIssueSeverity.WARNING,
        "tools",
        "zeta",
        message="Safe warning.",
    )
    second = PolicyConsistencyIssue(
        PolicyIssueCode.MISSING_DOMAIN,
        PolicyIssueSeverity.FATAL,
        "domains",
        "alpha",
        message="Safe failure.",
    )
    report = PolicyConsistencyReport((first, second))
    reverse = PolicyConsistencyReport((second, first))

    assert report == reverse
    assert report.issues[0] is second
    assert not report.ok
    assert not report.can_execute_tools
    with pytest.raises(FrozenInstanceError):
        report.issues = ()
    with pytest.raises(FrozenInstanceError):
        first.subject = "changed"


def test_unknown_intent_and_missing_domain_are_fatal() -> None:
    unknown = validate(intent_routes={"ghost": ("cap.read",)})
    missing = validate(domains=())
    assert PolicyIssueCode.UNKNOWN_INTENT in codes(unknown)
    assert PolicyIssueCode.MISSING_DOMAIN in codes(missing)


def test_disabled_domain_and_missing_domain_capability_are_fatal() -> None:
    disabled = validate(domains=(domain(enabled=False),))
    incomplete = validate(
        domains=(domain(capabilities=("cap.other",)),)
    )
    assert PolicyIssueCode.DISABLED_DOMAIN in codes(disabled)
    assert PolicyIssueCode.DOMAIN_CAPABILITY_MISSING in codes(incomplete)


def test_unknown_capability_and_capability_without_tool_are_accumulated() -> None:
    report = validate(
        intent_routes={"alpha": ("cap.missing",)},
        domains=(domain(capabilities=("cap.missing",)),),
    )
    assert PolicyIssueCode.UNKNOWN_CAPABILITY in codes(report)
    assert PolicyIssueCode.CAPABILITY_WITHOUT_TOOL in codes(report)


def test_noncontextual_tool_does_not_satisfy_route() -> None:
    report = validate(
        tools=(PolicyTool("reader", capabilities=("cap.read",)),),
    )
    assert PolicyIssueCode.CAPABILITY_WITHOUT_TOOL in codes(report)


def test_unknown_tool_and_ambiguous_tool_are_fatal() -> None:
    unknown = validate(domains=(domain(tool_names=("missing",)),))
    ambiguous = validate(
        tools=(
            base_values()["tools"][0],
            PolicyTool(
                "reader_two",
                capabilities=("cap.read",),
                routing_permission="READ",
                contextual=True,
                routing_metadata=True,
            ),
        ),
        permissions=(
            PolicyPermission("reader", "allow", "low"),
            PolicyPermission("reader_two", "allow", "low"),
        ),
    )
    assert PolicyIssueCode.TOOL_MISSING in codes(unknown)
    assert PolicyIssueCode.AMBIGUOUS_TOOL in codes(ambiguous)


def test_unknown_domain_is_fatal() -> None:
    tool = PolicyTool(
        "reader",
        domain="ghost",
        capabilities=("cap.read",),
        routing_permission="READ",
        contextual=True,
        routing_metadata=True,
    )
    assert PolicyIssueCode.UNKNOWN_DOMAIN in codes(validate(tools=(tool,)))


def test_missing_and_stale_permission_rules_are_fatal() -> None:
    missing = validate(permissions=())
    stale = validate(
        permissions=(
            PolicyPermission("reader", "allow", "low"),
            PolicyPermission("ghost", "allow", "low"),
        )
    )
    assert PolicyIssueCode.MISSING_PERMISSION_RULE in codes(missing)
    assert PolicyIssueCode.STALE_PERMISSION_RULE in codes(stale)


def test_invalid_permission_decision_and_unknown_risk_are_fatal() -> None:
    report = validate(
        permissions=(PolicyPermission("reader", "maybe", "mystery"),)
    )
    assert PolicyIssueCode.INVALID_PERMISSION_DECISION in codes(report)
    assert PolicyIssueCode.UNKNOWN_RISK_LEVEL in codes(report)


def test_risk_mismatch_and_automatic_confirmation_conflict_are_fatal() -> None:
    tool = PolicyTool(
        "reader",
        capabilities=("cap.read",),
        routing_permission="READ",
        risk="high",
        contextual=True,
        routing_metadata=True,
    )
    report = validate(
        tools=(tool,),
        permissions=(PolicyPermission("reader", "confirm", "low"),),
    )
    assert PolicyIssueCode.RISK_METADATA_MISMATCH in codes(report)
    assert PolicyIssueCode.AUTOMATIC_CONFIRMATION_CONFLICT in codes(report)


def test_denied_tool_is_not_available_to_route() -> None:
    report = validate(
        permissions=(PolicyPermission("reader", "deny", "low"),)
    )
    assert PolicyIssueCode.DENIED_TOOL_ROUTE in codes(report)
    assert PolicyIssueCode.CAPABILITY_WITHOUT_TOOL in codes(report)


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (
            model_policy(intent_profiles={"alpha": "ghost", "unknown": "code"}),
            PolicyIssueCode.UNKNOWN_MODEL_PROFILE,
        ),
        (
            model_policy(fallback_profile="ghost"),
            PolicyIssueCode.MISSING_FALLBACK_PROFILE,
        ),
        (
            model_policy(fallback_order=("ghost",)),
            PolicyIssueCode.INVALID_FALLBACK_PROFILE,
        ),
        (
            model_policy(context_budgets={"code": 1000, "ghost": 10}),
            PolicyIssueCode.INVALID_CONTEXT_BUDGET_PROFILE,
        ),
        (
            model_policy(context_budgets={}),
            PolicyIssueCode.MISSING_CONTEXT_BUDGET,
        ),
        (
            model_policy(intent_profiles={"unknown": "code"}),
            PolicyIssueCode.MISSING_INTENT_MODEL_MAPPING,
        ),
    ],
)
def test_model_policy_failures_are_structured(policy, expected) -> None:
    assert expected in codes(validate(model_policy=policy))


def test_extension_intent_uses_deterministic_model_fallback() -> None:
    report = validate(intents=("alpha", "beta", "unknown"))
    fallback = tuple(
        issue for issue in report.warnings
        if issue.code is PolicyIssueCode.INTENT_MODEL_FALLBACK
    )
    assert len(fallback) == 1
    assert fallback[0].subject == "beta"
    assert fallback[0].related_subject == "code"
    assert report.ok


def plugin_tool(
    name="plugin_reader",
    *,
    source="sample_plugin",
    domain_name="sample",
    active=True,
    routing_metadata=True,
) -> PolicyTool:
    return PolicyTool(
        name,
        source=source,
        domain=domain_name,
        capabilities=("cap.read",),
        routing_permission="READ",
        contextual=True,
        routing_metadata=routing_metadata,
        active=active,
    )


def test_builtin_plugin_and_plugin_plugin_collisions_are_fatal() -> None:
    builtin_plugin = validate(tools=(base_values()["tools"][0], plugin_tool("reader")))
    plugin_plugin = validate(
        tools=(plugin_tool("shared", source="one"), plugin_tool("shared", source="two"))
    )
    assert PolicyIssueCode.TOOL_COLLISION in codes(builtin_plugin)
    assert PolicyIssueCode.TOOL_COLLISION in codes(plugin_plugin)


def test_plugin_domain_capability_routing_and_permission_failures() -> None:
    unknown_domain = validate(tools=(base_values()["tools"][0], plugin_tool(domain_name="ghost")))
    capability = validate(
        domains=(domain(capabilities=("cap.other",)),),
        tools=(base_values()["tools"][0], plugin_tool()),
    )
    routing = validate(tools=(base_values()["tools"][0], plugin_tool(routing_metadata=False)))
    permission = validate(tools=(plugin_tool(),), permissions=())

    assert PolicyIssueCode.PLUGIN_DOMAIN_MISSING in codes(unknown_domain)
    assert PolicyIssueCode.PLUGIN_CAPABILITY_MISSING in codes(capability)
    assert PolicyIssueCode.PLUGIN_ROUTING_MISSING in codes(routing)
    assert PolicyIssueCode.PLUGIN_PERMISSION_MISSING in codes(permission)


def test_inactive_plugin_needs_no_permission_and_cannot_satisfy_route() -> None:
    activation = PluginToolActivation(
        "plugin_reader",
        "sample_plugin",
        "sample",
        PluginToolState.INACTIVE,
        ("permission_denied",),
    )
    report = validate(
        tools=(plugin_tool(active=False),),
        permissions=(),
        plugin_activations=(activation,),
        plugin_policy_enabled=True,
    )
    assert PolicyIssueCode.PLUGIN_PERMISSION_MISSING not in codes(report)
    assert PolicyIssueCode.INACTIVE_PLUGIN_ROUTE in codes(report)


def test_disabled_plugin_policy_cannot_publish_active_tools() -> None:
    activation = PluginToolActivation(
        "plugin_reader",
        "sample_plugin",
        "sample",
        PluginToolState.ACTIVE,
    )
    report = validate(
        tools=(base_values()["tools"][0], plugin_tool()),
        permissions=(
            PolicyPermission("reader", "allow", "low"),
            PolicyPermission("plugin_reader", "allow", "low"),
        ),
        plugin_activations=(activation,),
        plugin_policy_enabled=False,
    )
    assert PolicyIssueCode.PLUGIN_POLICY_DISABLED_ACTIVE_TOOLS in codes(report)


def test_report_accumulates_failures_without_leaking_callables_or_secrets() -> None:
    secret = lambda: "TOP-SECRET"  # noqa: E731
    issue = PolicyConsistencyIssue(
        PolicyIssueCode.CONFIGURATION_ERROR,
        PolicyIssueSeverity.FATAL,
        "config",
        "policy",
        message="Safe error.",
        details=((secret, secret),),  # type: ignore[arg-type]
    )
    report = PolicyConsistencyReport((issue, *validate(domains=(), permissions=()).issues))
    rendered = repr(report.to_safe_dict())

    assert len(report.fatal_issues) >= 3
    assert "TOP-SECRET" not in rendered
    assert "lambda" not in rendered
    assert "[redacted]" in rendered
