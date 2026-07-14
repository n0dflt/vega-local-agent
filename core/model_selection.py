"""Pure, deterministic model-profile selection for contextual requests."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from core.model_router import DEFAULT_PROFILE, MODEL_PROFILES


class ModelSelectionMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class ModelRoutingPolicyError(ValueError):
    """Raised when model routing policy cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ModelRoutingPolicy:
    enabled: bool
    fallback_profile: str
    intent_profiles: Mapping[str, str]
    fallback_order: tuple[str, ...]
    deep_request_chars: int
    deep_signals: tuple[str, ...]
    context_budgets: Mapping[str, int]
    head_ratio: float


@dataclass(frozen=True, slots=True)
class ModelSelectionDecision:
    mode: ModelSelectionMode
    intent: str
    profile: str
    model: str
    reason: str
    requested_profile: str
    fallback_used: bool = False
    available: bool = True


_REQUIRED_KEYS = frozenset(
    {
        "enabled",
        "fallback_profile",
        "intent_profiles",
        "fallback_order",
        "deep_request_chars",
        "deep_signals",
        "context_budgets",
        "head_ratio",
    }
)
_KNOWN_INTENTS = frozenset(
    {
        "document_analysis",
        "project_search",
        "bug_fix",
        "test_run",
        "code_review",
        "documentation_update",
        "release_check",
        "unknown",
    }
)


def load_model_routing_policy(
    source: ModelRoutingPolicy | Mapping[str, Any] | str | Path,
) -> ModelRoutingPolicy:
    """Load and strictly validate a fail-closed model routing policy."""

    if isinstance(source, ModelRoutingPolicy):
        return source
    if isinstance(source, Mapping):
        data = dict(source)
    else:
        try:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise ModelRoutingPolicyError(
                f"cannot load model routing policy: {exc}"
            ) from exc

    if not isinstance(data, dict):
        raise ModelRoutingPolicyError("model routing policy must be an object")

    missing = _REQUIRED_KEYS - data.keys()
    unknown = data.keys() - _REQUIRED_KEYS
    if missing:
        raise ModelRoutingPolicyError(
            "missing model routing policy fields: " + ", ".join(sorted(missing))
        )
    if unknown:
        raise ModelRoutingPolicyError(
            "unknown model routing policy fields: " + ", ".join(sorted(unknown))
        )

    enabled = data["enabled"]
    if type(enabled) is not bool:
        raise ModelRoutingPolicyError("enabled must be a boolean")

    fallback_profile = _validate_profile(
        data["fallback_profile"], "fallback_profile"
    )
    intent_profiles = _validate_profile_map(data["intent_profiles"])
    if set(intent_profiles) != _KNOWN_INTENTS:
        raise ModelRoutingPolicyError(
            "intent_profiles must contain exactly: "
            + ", ".join(sorted(_KNOWN_INTENTS))
        )
    if intent_profiles["unknown"] != fallback_profile:
        raise ModelRoutingPolicyError(
            "intent_profiles.unknown must equal fallback_profile"
        )
    fallback_order = _validate_profile_sequence(
        data["fallback_order"], "fallback_order", allow_empty=False
    )
    deep_signals = _validate_string_sequence(
        data["deep_signals"], "deep_signals"
    )

    deep_request_chars = data["deep_request_chars"]
    if (
        type(deep_request_chars) is not int
        or deep_request_chars <= 0
    ):
        raise ModelRoutingPolicyError(
            "deep_request_chars must be a positive integer"
        )

    budgets_data = data["context_budgets"]
    if not isinstance(budgets_data, Mapping):
        raise ModelRoutingPolicyError("context_budgets must be an object")
    if set(budgets_data) != set(MODEL_PROFILES):
        raise ModelRoutingPolicyError(
            "context_budgets must contain exactly: "
            + ", ".join(sorted(MODEL_PROFILES))
        )
    context_budgets: dict[str, int] = {}
    for profile, value in budgets_data.items():
        if type(value) is not int or value <= 0:
            raise ModelRoutingPolicyError(
                f"context_budgets.{profile} must be a positive integer"
            )
        context_budgets[profile] = value

    head_ratio = data["head_ratio"]
    if (
        isinstance(head_ratio, bool)
        or not isinstance(head_ratio, (int, float))
        or not 0.0 < float(head_ratio) < 1.0
    ):
        raise ModelRoutingPolicyError("head_ratio must be between 0 and 1")

    return ModelRoutingPolicy(
        enabled=enabled,
        fallback_profile=fallback_profile,
        intent_profiles=dict(intent_profiles),
        fallback_order=fallback_order,
        deep_request_chars=deep_request_chars,
        deep_signals=deep_signals,
        context_budgets=dict(context_budgets),
        head_ratio=float(head_ratio),
    )


def select_model(
    intent: str | Enum,
    policy: ModelRoutingPolicy,
    installed_models: Sequence[str],
    *,
    selection_mode: ModelSelectionMode | str = ModelSelectionMode.AUTO,
    current_profile: str = DEFAULT_PROFILE,
    explicit_model: str = "",
    request_text: str = "",
) -> ModelSelectionDecision:
    """Choose a model without I/O or direct Ollama access."""

    if not isinstance(policy, ModelRoutingPolicy):
        raise TypeError("policy must be a ModelRoutingPolicy")
    try:
        mode = ModelSelectionMode(selection_mode)
    except ValueError as exc:
        raise ValueError(f"unknown model selection mode: {selection_mode}") from exc
    current_profile = _validate_profile(current_profile, "current_profile")
    intent_name = str(getattr(intent, "value", intent)).strip().lower()
    installed = frozenset(str(item).strip() for item in installed_models)

    override = str(explicit_model or "").strip()
    if override:
        if override in MODEL_PROFILES:
            profile = override
            model = MODEL_PROFILES[profile]["model"]
        else:
            profile = next(
                (
                    name
                    for name, details in MODEL_PROFILES.items()
                    if details["model"] == override
                ),
                "explicit",
            )
            model = override
        return ModelSelectionDecision(
            mode=mode,
            intent=intent_name,
            profile=profile,
            model=model,
            reason="Explicit model override has highest priority.",
            requested_profile=profile,
            available=True,
        )

    if mode is ModelSelectionMode.MANUAL or not policy.enabled:
        requested_profile = current_profile
        basis = (
            "Manual selection uses the stored profile."
            if mode is ModelSelectionMode.MANUAL
            else "Automatic routing is disabled; using the stored fallback profile."
        )
    else:
        requested_profile = (
            policy.fallback_profile
            if intent_name == "unknown"
            else policy.intent_profiles.get(intent_name, policy.fallback_profile)
        )
        basis = (
            f"Intent '{intent_name}' maps to profile '{requested_profile}'."
            if intent_name in policy.intent_profiles
            else f"Unknown intent uses fallback profile '{requested_profile}'."
        )
        normalized_request = str(request_text or "").lower()
        deep_signal = next(
            (signal for signal in policy.deep_signals if signal in normalized_request),
            "",
        )
        if requested_profile != "deep" and (
            len(normalized_request) >= policy.deep_request_chars or deep_signal
        ):
            requested_profile = "deep"
            basis = (
                "Request complexity policy selected profile 'deep' "
                + (
                    f"because signal '{deep_signal}' was present."
                    if deep_signal
                    else "because the request reached the configured character threshold."
                )
            )

    candidates = _unique_profiles(
        (requested_profile, *policy.fallback_order, policy.fallback_profile)
    )
    for profile in candidates:
        model = MODEL_PROFILES[profile]["model"]
        if model in installed:
            fallback_used = profile != requested_profile
            reason = basis
            if fallback_used:
                reason += (
                    f" Requested model is unavailable; fallback profile '{profile}' "
                    "is installed."
                )
            return ModelSelectionDecision(
                mode=mode,
                intent=intent_name,
                profile=profile,
                model=model,
                reason=reason,
                requested_profile=requested_profile,
                fallback_used=fallback_used,
                available=True,
            )

    return ModelSelectionDecision(
        mode=mode,
        intent=intent_name,
        profile=requested_profile,
        model="",
        reason=basis + " No allowed model from the fallback order is installed.",
        requested_profile=requested_profile,
        fallback_used=False,
        available=False,
    )


def _validate_profile(value: Any, field: str) -> str:
    if not isinstance(value, str) or value not in MODEL_PROFILES:
        raise ModelRoutingPolicyError(
            f"{field} must name a profile from MODEL_PROFILES"
        )
    return value


def _validate_profile_map(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ModelRoutingPolicyError("intent_profiles must be a non-empty object")
    result: dict[str, str] = {}
    for intent, profile in value.items():
        if not isinstance(intent, str) or not intent.strip():
            raise ModelRoutingPolicyError(
                "intent_profiles keys must be non-empty strings"
            )
        result[intent] = _validate_profile(
            profile, f"intent_profiles.{intent}"
        )
    return result


def _validate_profile_sequence(
    value: Any, field: str, *, allow_empty: bool
) -> tuple[str, ...]:
    values = _validate_string_sequence(value, field)
    if not values and not allow_empty:
        raise ModelRoutingPolicyError(f"{field} must not be empty")
    if len(set(values)) != len(values):
        raise ModelRoutingPolicyError(f"{field} must not contain duplicates")
    for index, profile in enumerate(values):
        _validate_profile(profile, f"{field}[{index}]")
    return values


def _validate_string_sequence(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ModelRoutingPolicyError(f"{field} must be an array of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ModelRoutingPolicyError(
                f"{field} must contain only non-empty strings"
            )
        result.append(item.strip().lower())
    return tuple(result)


def _unique_profiles(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


select_model_profile = select_model


__all__ = [
    "ModelRoutingPolicy",
    "ModelRoutingPolicyError",
    "ModelSelectionDecision",
    "ModelSelectionMode",
    "load_model_routing_policy",
    "select_model",
    "select_model_profile",
]
