"""Immutable, non-executing production configuration snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.contextual_router import (
    ContextualRoutingError,
    ToolRoutingPolicy,
    load_tool_routing_policy,
)
from core.intent_analyzer import IntentType
from core.model_router import MODEL_PROFILES
from core.model_selection import (
    ModelRoutingPolicy,
    ModelRoutingPolicyError,
    load_model_routing_policy,
)
from core.policy_consistency import (
    PolicyConsistencyReport,
    PolicyPermission,
    PolicyTool,
    configuration_error_report,
    validate_policy_consistency,
)
from core.tool_catalog import ToolCatalogError, load_tool_capabilities
from core.tool_planner import _INTENT_ROUTES
from domains.builtin import build_builtin_domain_registry
from domains.models import DomainDefinition
from permissions.models import PermissionPolicy, PermissionPolicyError
from permissions.policy import load_permission_policy
from plugins.bootstrap import (
    PluginBootstrapError,
    PluginBootstrapResult,
    bootstrap_plugins,
)
from plugins.models import PluginToolActivation
from plugins.policy import PluginPolicyError, load_plugin_policy
from tools.registry import BUILTIN_TOOL_REGISTRY


@dataclass(frozen=True, slots=True)
class RoutingPolicySnapshot:
    enabled: bool
    automatic_permissions: tuple[str, ...]
    confirmation_permissions: tuple[str, ...]
    max_tool_steps: int
    fail_closed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "automatic_permissions", tuple(self.automatic_permissions))
        object.__setattr__(
            self,
            "confirmation_permissions",
            tuple(self.confirmation_permissions),
        )


@dataclass(frozen=True, slots=True)
class ModelPolicySnapshot:
    enabled: bool
    fallback_profile: str
    intent_profiles: tuple[tuple[str, str], ...]
    fallback_order: tuple[str, ...]
    context_budgets: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent_profiles", tuple(self.intent_profiles))
        object.__setattr__(self, "fallback_order", tuple(self.fallback_order))
        object.__setattr__(self, "context_budgets", tuple(self.context_budgets))


@dataclass(frozen=True, slots=True)
class ProductionSnapshot:
    domains: tuple[DomainDefinition, ...]
    intents: tuple[str, ...]
    capabilities: tuple[str, ...]
    routing: RoutingPolicySnapshot | None
    tools: tuple[PolicyTool, ...]
    permissions: tuple[PolicyPermission, ...]
    model_policy: ModelPolicySnapshot | None
    plugin_activations: tuple[PluginToolActivation, ...]
    consistency_report: PolicyConsistencyReport

    def __post_init__(self) -> None:
        object.__setattr__(self, "domains", tuple(self.domains))
        object.__setattr__(self, "intents", tuple(self.intents))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "tools", tuple(self.tools))
        object.__setattr__(self, "permissions", tuple(self.permissions))
        object.__setattr__(self, "plugin_activations", tuple(self.plugin_activations))

    @property
    def can_execute_tools(self) -> bool:
        return self.consistency_report.can_execute_tools

    @property
    def effective_tool_names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)


def _routing_snapshot(policy: ToolRoutingPolicy) -> RoutingPolicySnapshot:
    return RoutingPolicySnapshot(
        enabled=policy.enabled,
        automatic_permissions=policy.automatic_permissions,
        confirmation_permissions=policy.confirmation_permissions,
        max_tool_steps=policy.max_tool_steps,
        fail_closed=policy.fail_closed,
    )


def _model_snapshot(policy: ModelRoutingPolicy) -> ModelPolicySnapshot:
    return ModelPolicySnapshot(
        enabled=policy.enabled,
        fallback_profile=policy.fallback_profile,
        intent_profiles=tuple(sorted(policy.intent_profiles.items())),
        fallback_order=policy.fallback_order,
        context_budgets=tuple(sorted(policy.context_budgets.items())),
    )


def _permissions(policy: PermissionPolicy) -> tuple[PolicyPermission, ...]:
    return tuple(
        PolicyPermission(
            tool_name=rule.tool_name,
            effect=rule.effect.value,
            risk=rule.risk.value,
            capabilities=tuple(capability.value for capability in rule.capabilities),
        )
        for rule in sorted(policy.rules, key=lambda item: item.tool_name)
    )


def _normalized_tools(
    capability_config,
    bootstrap: PluginBootstrapResult,
) -> tuple[PolicyTool, ...]:
    values: list[PolicyTool] = []
    activation_by_name = {
        activation.tool_name: activation for activation in bootstrap.activations
    }

    for name in sorted(BUILTIN_TOOL_REGISTRY):
        metadata = capability_config.get(name)
        configured = isinstance(metadata, dict)
        values.append(
            PolicyTool(
                name=name,
                capabilities=(
                    tuple(metadata.get("capabilities", ())) if configured else ()
                ),
                routing_permission=(
                    str(metadata.get("permission", "")) if configured else ""
                ),
                contextual=configured,
                routing_metadata=configured,
            )
        )

    for manifest in bootstrap.manifests:
        for tool in manifest.tools:
            activation = activation_by_name[tool.name]
            values.append(
                PolicyTool(
                    name=tool.name,
                    source=manifest.name,
                    domain=tool.domain,
                    capabilities=tool.capabilities,
                    routing_permission=tool.permission,
                    contextual=True,
                    routing_metadata=tool.name in capability_config,
                    active=activation.active,
                )
            )
    return tuple(sorted(values, key=lambda tool: (tool.name, tool.source)))


def _empty_snapshot(report: PolicyConsistencyReport) -> ProductionSnapshot:
    return ProductionSnapshot(
        domains=(),
        intents=(),
        capabilities=(),
        routing=None,
        tools=(),
        permissions=(),
        model_policy=None,
        plugin_activations=(),
        consistency_report=report,
    )


def build_production_snapshot(project_root: Path) -> ProductionSnapshot:
    """Load and validate production metadata without publishing or executing it."""

    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a pathlib.Path")
    root = project_root.resolve()

    try:
        domain_registry = build_builtin_domain_registry()
        capability_config = load_tool_capabilities(
            root / "config" / "tool_capabilities.json"
        )
        routing_policy = load_tool_routing_policy(
            root / "config" / "tool_routing_policy.json"
        )
        permission_policy = load_permission_policy(root)
        model_policy = load_model_routing_policy(
            root / "config" / "model_routing_policy.json"
        )
        plugin_policy = load_plugin_policy(root / "config" / "plugin_policy.json")
        bootstrap = bootstrap_plugins(
            root / "config" / "plugin_policy.json",
            domain_registry,
            project_root=root,
            builtin_tools=BUILTIN_TOOL_REGISTRY,
            capability_config=capability_config,
            permission_policy=permission_policy,
        )
    except (
        ContextualRoutingError,
        ModelRoutingPolicyError,
        PermissionPolicyError,
        PluginBootstrapError,
        PluginPolicyError,
        ToolCatalogError,
        OSError,
        ValueError,
    ) as exc:
        return _empty_snapshot(
            configuration_error_report(
                layer="production_snapshot",
                subject="project_configuration",
                exception_type=type(exc).__name__,
            )
        )

    try:
        domains = domain_registry.list_domains()
        intents = tuple(sorted(intent.value for intent in IntentType))
        intent_routes = {
            intent.value: tuple(capabilities)
            for intent, capabilities in _INTENT_ROUTES.items()
        }
        permissions = _permissions(permission_policy)
        all_tools = _normalized_tools(capability_config, bootstrap)
        configured_capabilities = frozenset(
            capability
            for tool in all_tools
            if tool.contextual
            for capability in tool.capabilities
        )
        active_intents = tuple(
            intent
            for intent, required in intent_routes.items()
            if all(capability in configured_capabilities for capability in required)
        )
        report = validate_policy_consistency(
            intents=intents,
            intent_routes=intent_routes,
            domains=domains,
            tools=all_tools,
            permissions=permissions,
            routing_policy=routing_policy,
            model_policy=model_policy,
            known_model_profiles=MODEL_PROFILES,
            plugin_activations=bootstrap.activations,
            plugin_policy_enabled=plugin_policy.enabled,
            active_intents=active_intents,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _empty_snapshot(
            configuration_error_report(
                layer="production_snapshot",
                subject="normalized_metadata",
                exception_type=type(exc).__name__,
            )
        )
    permission_effects = {item.tool_name: item.effect for item in permissions}
    effective_tools = tuple(
        tool for tool in all_tools
        if tool.active and permission_effects.get(tool.name) in {"allow", "confirm"}
    )
    capabilities = tuple(
        sorted({capability for tool in effective_tools for capability in tool.capabilities})
    )

    return ProductionSnapshot(
        domains=domains,
        intents=intents,
        capabilities=capabilities,
        routing=_routing_snapshot(routing_policy),
        tools=effective_tools,
        permissions=permissions,
        model_policy=_model_snapshot(model_policy),
        plugin_activations=bootstrap.activations,
        consistency_report=report,
    )


__all__ = [
    "ModelPolicySnapshot",
    "ProductionSnapshot",
    "RoutingPolicySnapshot",
    "build_production_snapshot",
]
