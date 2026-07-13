"""Pure cross-layer validation for immutable VEGA production metadata."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.contextual_router import ToolRoutingPolicy
from core.model_selection import ModelRoutingPolicy
from domains.models import DomainDefinition
from plugins.models import PluginToolActivation


class PolicyIssueSeverity(str, Enum):
    FATAL = "fatal"
    DEGRADED = "degraded"
    WARNING = "warning"


class PolicyIssueCode(str, Enum):
    CONFIGURATION_ERROR = "configuration_error"
    UNKNOWN_INTENT = "unknown_intent"
    INACTIVE_INTENT_ROUTE = "inactive_intent_route"
    MISSING_DOMAIN = "missing_domain"
    AMBIGUOUS_DOMAIN = "ambiguous_domain"
    UNKNOWN_DOMAIN = "unknown_domain"
    DISABLED_DOMAIN = "disabled_domain"
    DOMAIN_CAPABILITY_MISSING = "domain_capability_missing"
    UNKNOWN_CAPABILITY = "unknown_capability"
    CAPABILITY_WITHOUT_TOOL = "capability_without_tool"
    TOOL_MISSING = "tool_missing"
    AMBIGUOUS_TOOL = "ambiguous_tool"
    INACTIVE_PLUGIN_ROUTE = "inactive_plugin_route"
    MISSING_PERMISSION_RULE = "missing_permission_rule"
    STALE_PERMISSION_RULE = "stale_permission_rule"
    INVALID_PERMISSION_DECISION = "invalid_permission_decision"
    UNKNOWN_RISK_LEVEL = "unknown_risk_level"
    RISK_METADATA_MISMATCH = "risk_metadata_mismatch"
    AUTOMATIC_CONFIRMATION_CONFLICT = "automatic_confirmation_conflict"
    DENIED_TOOL_ROUTE = "denied_tool_route"
    UNKNOWN_MODEL_PROFILE = "unknown_model_profile"
    MISSING_FALLBACK_PROFILE = "missing_fallback_profile"
    INVALID_FALLBACK_PROFILE = "invalid_fallback_profile"
    INVALID_CONTEXT_BUDGET_PROFILE = "invalid_context_budget_profile"
    MISSING_CONTEXT_BUDGET = "missing_context_budget"
    MISSING_INTENT_MODEL_MAPPING = "missing_intent_model_mapping"
    INTENT_MODEL_FALLBACK = "intent_model_fallback"
    PLUGIN_DOMAIN_MISSING = "plugin_domain_missing"
    PLUGIN_CAPABILITY_MISSING = "plugin_capability_missing"
    TOOL_COLLISION = "tool_collision"
    PLUGIN_PERMISSION_MISSING = "plugin_permission_missing"
    PLUGIN_ROUTING_MISSING = "plugin_routing_missing"
    PLUGIN_POLICY_DISABLED_ACTIVE_TOOLS = "plugin_policy_disabled_active_tools"


_EFFECTS = frozenset({"allow", "confirm", "deny"})
_RISKS = frozenset({"low", "medium", "high", "critical"})
_SEVERITY_ORDER = {
    PolicyIssueSeverity.FATAL: 0,
    PolicyIssueSeverity.DEGRADED: 1,
    PolicyIssueSeverity.WARNING: 2,
}


@dataclass(frozen=True, slots=True)
class PolicyTool:
    """Callable-free normalized tool metadata used only for validation."""

    name: str
    source: str = "builtin"
    domain: str = ""
    capabilities: tuple[str, ...] = ()
    routing_permission: str = ""
    risk: str = ""
    contextual: bool = False
    routing_metadata: bool = False
    active: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", tuple(self.capabilities))

    @property
    def plugin(self) -> bool:
        return self.source != "builtin"


@dataclass(frozen=True, slots=True)
class PolicyPermission:
    """Safe permission metadata without reason text or confirmation token."""

    tool_name: str
    effect: str
    risk: str
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", tuple(self.capabilities))


@dataclass(frozen=True, slots=True)
class PolicyConsistencyIssue:
    code: PolicyIssueCode
    severity: PolicyIssueSeverity
    layer: str
    subject: str
    related_subject: str = ""
    message: str = ""
    details: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        safe_details: list[tuple[str, str]] = []
        for key, value in self.details:
            safe_key = key if isinstance(key, str) else "detail"
            safe_value = (
                str(value)
                if isinstance(value, (str, int, float, bool))
                else "[redacted]"
            )
            safe_details.append((safe_key[:64], safe_value[:256]))
        object.__setattr__(self, "details", tuple(sorted(safe_details)))

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "layer": self.layer,
            "subject": self.subject,
            "related_subject": self.related_subject,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class PolicyConsistencyReport:
    issues: tuple[PolicyConsistencyIssue, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(
                self.issues,
                key=lambda issue: (
                    _SEVERITY_ORDER[issue.severity],
                    issue.code.value,
                    issue.layer,
                    issue.subject,
                    issue.related_subject,
                    issue.details,
                ),
            )
        )
        object.__setattr__(self, "issues", ordered)

    @property
    def fatal_issues(self) -> tuple[PolicyConsistencyIssue, ...]:
        return tuple(
            issue for issue in self.issues
            if issue.severity is PolicyIssueSeverity.FATAL
        )

    @property
    def degraded_issues(self) -> tuple[PolicyConsistencyIssue, ...]:
        return tuple(
            issue for issue in self.issues
            if issue.severity is PolicyIssueSeverity.DEGRADED
        )

    @property
    def warnings(self) -> tuple[PolicyConsistencyIssue, ...]:
        return tuple(
            issue for issue in self.issues
            if issue.severity is PolicyIssueSeverity.WARNING
        )

    @property
    def ok(self) -> bool:
        return not self.fatal_issues

    @property
    def can_execute_tools(self) -> bool:
        return not self.fatal_issues

    @property
    def summary(self) -> str:
        return (
            f"fatal={len(self.fatal_issues)}; "
            f"degraded={len(self.degraded_issues)}; "
            f"warning={len(self.warnings)}"
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "can_execute_tools": self.can_execute_tools,
            "summary": self.summary,
            "issues": [issue.to_safe_dict() for issue in self.issues],
        }


def configuration_error_report(
    *,
    layer: str,
    subject: str,
    exception_type: str,
) -> PolicyConsistencyReport:
    """Build a safe fatal report without exposing exception arguments."""

    return PolicyConsistencyReport(
        (
            PolicyConsistencyIssue(
                code=PolicyIssueCode.CONFIGURATION_ERROR,
                severity=PolicyIssueSeverity.FATAL,
                layer=layer,
                subject=subject,
                message="Production configuration could not be validated.",
                details=(("exception_type", exception_type),),
            ),
        )
    )


def validate_policy_consistency(
    *,
    intents: Iterable[str],
    intent_routes: Mapping[str, Iterable[str]],
    domains: Iterable[DomainDefinition],
    tools: Iterable[PolicyTool],
    permissions: Iterable[PolicyPermission],
    routing_policy: ToolRoutingPolicy,
    model_policy: ModelRoutingPolicy,
    known_model_profiles: Iterable[str],
    plugin_activations: Iterable[PluginToolActivation] = (),
    plugin_policy_enabled: bool = False,
    active_intents: Iterable[str] | None = None,
) -> PolicyConsistencyReport:
    """Validate normalized metadata without imports, I/O, tools, or models."""

    intent_names = frozenset(str(value) for value in intents)
    route_map = {
        str(intent): tuple(str(capability) for capability in capabilities)
        for intent, capabilities in intent_routes.items()
    }
    active_intent_names = frozenset(
        route_map if active_intents is None else (str(value) for value in active_intents)
    )
    domain_values = tuple(domains)
    tool_values = tuple(tools)
    permission_values = tuple(permissions)
    activation_values = tuple(plugin_activations)
    profiles = frozenset(str(value) for value in known_model_profiles)
    issues: list[PolicyConsistencyIssue] = []

    def add(
        code: PolicyIssueCode,
        layer: str,
        subject: str,
        *,
        related: str = "",
        severity: PolicyIssueSeverity = PolicyIssueSeverity.FATAL,
        message: str,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        issues.append(
            PolicyConsistencyIssue(
                code=code,
                severity=severity,
                layer=layer,
                subject=subject,
                related_subject=related,
                message=message,
                details=details,
            )
        )

    tools_by_name: dict[str, list[PolicyTool]] = defaultdict(list)
    for tool in tool_values:
        tools_by_name[tool.name].append(tool)
    for name, named_tools in tools_by_name.items():
        if len(named_tools) > 1:
            add(
                PolicyIssueCode.TOOL_COLLISION,
                "plugins",
                name,
                message="A tool name is published by more than one source.",
                details=(("sources", ",".join(sorted(t.source for t in named_tools))),),
            )

    domain_by_name = {domain.name: domain for domain in domain_values}
    permission_by_tool = {permission.tool_name: permission for permission in permission_values}

    for intent in sorted(route_map):
        if intent not in intent_names:
            add(
                PolicyIssueCode.UNKNOWN_INTENT,
                "routing",
                intent,
                message="Routing metadata references an unknown intent.",
            )
            continue
        if intent not in active_intent_names:
            add(
                PolicyIssueCode.INACTIVE_INTENT_ROUTE,
                "routing",
                intent,
                severity=PolicyIssueSeverity.DEGRADED,
                message="The planner route is unavailable to automatic contextual routing.",
            )
            continue
        owners = tuple(domain for domain in domain_values if intent in domain.intents)
        if not owners:
            add(
                PolicyIssueCode.MISSING_DOMAIN,
                "domains",
                intent,
                message="An active intent is not owned by a domain.",
            )
            continue
        enabled_owners = tuple(domain for domain in owners if domain.enabled)
        if not enabled_owners:
            add(
                PolicyIssueCode.DISABLED_DOMAIN,
                "domains",
                intent,
                related=owners[0].name,
                message="The intent is owned only by disabled domains.",
            )
            continue
        if len(enabled_owners) > 1:
            add(
                PolicyIssueCode.AMBIGUOUS_DOMAIN,
                "domains",
                intent,
                message="More than one enabled domain owns the intent.",
                details=(("domains", ",".join(sorted(d.name for d in enabled_owners))),),
            )
        for domain in enabled_owners:
            for capability in route_map[intent]:
                if capability not in domain.capabilities:
                    add(
                        PolicyIssueCode.DOMAIN_CAPABILITY_MISSING,
                        "domains",
                        domain.name,
                        related=capability,
                        message="A domain does not declare a capability required by its intent.",
                    )

    all_tool_names = frozenset(tools_by_name)
    for domain in domain_values:
        for tool_name in domain.tool_names:
            if tool_name not in all_tool_names:
                add(
                    PolicyIssueCode.TOOL_MISSING,
                    "domains",
                    domain.name,
                    related=tool_name,
                    message="Domain metadata references an unavailable tool.",
                )

    for tool in tool_values:
        if tool.domain and tool.domain not in domain_by_name:
            add(
                PolicyIssueCode.PLUGIN_DOMAIN_MISSING if tool.plugin
                else PolicyIssueCode.UNKNOWN_DOMAIN,
                "plugins" if tool.plugin else "domains",
                tool.name,
                related=tool.domain,
                message="Tool metadata references an unknown domain.",
            )
        if tool.plugin and not tool.routing_metadata:
            add(
                PolicyIssueCode.PLUGIN_ROUTING_MISSING,
                "plugins",
                tool.name,
                message="A plugin tool has no contextual routing metadata.",
            )
        if tool.plugin and tool.domain in domain_by_name:
            domain = domain_by_name[tool.domain]
            for capability in tool.capabilities:
                if capability not in domain.capabilities:
                    add(
                        PolicyIssueCode.PLUGIN_CAPABILITY_MISSING,
                        "plugins",
                        tool.name,
                        related=capability,
                        message="A plugin capability is not declared by its domain.",
                    )

    all_capabilities = frozenset(
        capability for tool in tool_values for capability in tool.capabilities
    )
    for intent, required in sorted(route_map.items()):
        if intent not in intent_names or intent not in active_intent_names:
            continue
        for capability in required:
            candidates = tuple(
                tool for tool in tool_values
                if tool.contextual and capability in tool.capabilities
            )
            if capability not in all_capabilities:
                add(
                    PolicyIssueCode.UNKNOWN_CAPABILITY,
                    "capabilities",
                    capability,
                    related=intent,
                    message="A route requires a capability unknown to all tools.",
                )
            eligible = tuple(
                tool for tool in candidates
                if tool.active
                and permission_by_tool.get(tool.name) is not None
                and permission_by_tool[tool.name].effect != "deny"
            )
            if not eligible:
                code = (
                    PolicyIssueCode.INACTIVE_PLUGIN_ROUTE
                    if candidates and any(tool.plugin and not tool.active for tool in candidates)
                    else PolicyIssueCode.CAPABILITY_WITHOUT_TOOL
                )
                add(
                    code,
                    "capabilities",
                    capability,
                    related=intent,
                    message="No active permitted tool provides a required capability.",
                )
            elif len(eligible) > 1:
                add(
                    PolicyIssueCode.AMBIGUOUS_TOOL,
                    "capabilities",
                    capability,
                    related=intent,
                    message="More than one active tool provides a required capability.",
                    details=(("tools", ",".join(sorted(t.name for t in eligible))),),
                )

    for tool in tool_values:
        if not tool.active:
            continue
        permission = permission_by_tool.get(tool.name)
        if permission is None:
            add(
                PolicyIssueCode.PLUGIN_PERMISSION_MISSING if tool.plugin
                else PolicyIssueCode.MISSING_PERMISSION_RULE,
                "permissions",
                tool.name,
                message="An executable tool has no permission rule.",
            )
            continue
        if permission.effect not in _EFFECTS:
            add(
                PolicyIssueCode.INVALID_PERMISSION_DECISION,
                "permissions",
                tool.name,
                related=permission.effect,
                message="Permission metadata contains an unknown decision.",
            )
        if permission.risk not in _RISKS:
            add(
                PolicyIssueCode.UNKNOWN_RISK_LEVEL,
                "permissions",
                tool.name,
                related=permission.risk,
                message="Permission metadata contains an unknown risk level.",
            )
        if tool.risk and permission.risk in _RISKS and tool.risk != permission.risk:
            add(
                PolicyIssueCode.RISK_METADATA_MISMATCH,
                "permissions",
                tool.name,
                related=permission.risk,
                message="Tool and permission risk metadata disagree.",
                details=(("tool_risk", tool.risk),),
            )
        if tool.contextual and permission.effect == "deny":
            add(
                PolicyIssueCode.DENIED_TOOL_ROUTE,
                "permissions",
                tool.name,
                message="A denied tool cannot be used by contextual routing.",
            )
        if (
            tool.contextual
            and tool.routing_permission in routing_policy.automatic_permissions
            and permission.effect == "confirm"
        ):
            add(
                PolicyIssueCode.AUTOMATIC_CONFIRMATION_CONFLICT,
                "permissions",
                tool.name,
                message="An automatic route targets a confirm-required tool.",
            )

    for permission in permission_values:
        if permission.tool_name not in all_tool_names:
            add(
                PolicyIssueCode.STALE_PERMISSION_RULE,
                "permissions",
                permission.tool_name,
                message="A permission rule references an unavailable tool.",
            )

    if model_policy.fallback_profile not in profiles:
        add(
            PolicyIssueCode.MISSING_FALLBACK_PROFILE,
            "models",
            model_policy.fallback_profile,
            message="The model fallback profile is unknown.",
        )
    for profile in model_policy.fallback_order:
        if profile not in profiles:
            add(
                PolicyIssueCode.INVALID_FALLBACK_PROFILE,
                "models",
                profile,
                message="Fallback order references an unknown model profile.",
            )
    for profile in model_policy.context_budgets:
        if profile not in profiles:
            add(
                PolicyIssueCode.INVALID_CONTEXT_BUDGET_PROFILE,
                "models",
                profile,
                message="A context budget references an unknown model profile.",
            )
    for profile in profiles:
        if profile not in model_policy.context_budgets:
            add(
                PolicyIssueCode.MISSING_CONTEXT_BUDGET,
                "models",
                profile,
                message="A known model profile has no context budget.",
            )
    for intent in sorted(intent_names):
        mapped_profile = model_policy.intent_profiles.get(intent)
        if mapped_profile is None:
            if intent in route_map:
                add(
                    PolicyIssueCode.MISSING_INTENT_MODEL_MAPPING,
                    "models",
                    intent,
                    message="A built-in routed intent has no model mapping.",
                )
            elif model_policy.fallback_profile in profiles:
                add(
                    PolicyIssueCode.INTENT_MODEL_FALLBACK,
                    "models",
                    intent,
                    related=model_policy.fallback_profile,
                    severity=PolicyIssueSeverity.WARNING,
                    message="An extension intent deterministically uses the fallback profile.",
                )
        elif mapped_profile not in profiles:
            add(
                PolicyIssueCode.UNKNOWN_MODEL_PROFILE,
                "models",
                intent,
                related=mapped_profile,
                message="An intent maps to an unknown model profile.",
            )
    for intent in model_policy.intent_profiles:
        if intent not in intent_names:
            add(
                PolicyIssueCode.UNKNOWN_INTENT,
                "models",
                intent,
                message="Model routing metadata references an unknown intent.",
            )

    active_plugin_names = frozenset(
        activation.tool_name for activation in activation_values if activation.active
    )
    if not plugin_policy_enabled and active_plugin_names:
        add(
            PolicyIssueCode.PLUGIN_POLICY_DISABLED_ACTIVE_TOOLS,
            "plugins",
            ",".join(sorted(active_plugin_names)),
            message="Disabled plugin policy produced active plugin tools.",
        )

    return PolicyConsistencyReport(tuple(issues))


__all__ = [
    "PolicyConsistencyIssue",
    "PolicyConsistencyReport",
    "PolicyIssueCode",
    "PolicyIssueSeverity",
    "PolicyPermission",
    "PolicyTool",
    "configuration_error_report",
    "validate_policy_consistency",
]
