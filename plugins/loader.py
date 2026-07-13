"""Manifest-only loader for allowlisted modules under trusted project roots."""

from __future__ import annotations

from pathlib import Path

from domains.registry import DomainRegistry
from plugins.models import PluginManifest, PluginValidationError
from plugins.module_resolver import ModuleResolutionError, resolve_module
from plugins.policy import PluginPolicy
from plugins.validation import (
    validate_manifest_domains,
    validate_module_allowed,
    validate_module_name,
    validate_plugin_manifest,
)


class PluginLoadError(RuntimeError):
    """Raised when a trusted plugin manifest cannot be loaded safely."""


def _is_relative_to(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_trusted_roots(
    project_root: str | Path,
    policy: PluginPolicy,
) -> tuple[Path, ...]:
    """Resolve existing policy roots without permitting project-root escape."""

    if not isinstance(policy, PluginPolicy):
        raise PluginLoadError("policy must be a PluginPolicy")
    if not policy.trusted_roots:
        raise PluginLoadError("enabled plugin policy requires trusted_roots")
    try:
        root = Path(project_root).resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        raise PluginLoadError(
            f"project_root cannot be resolved: {type(exc).__name__}: {exc}"
        ) from exc
    if not root.is_dir():
        raise PluginLoadError("project_root must be an existing directory")
    resolved: list[Path] = []
    for relative_root in policy.trusted_roots:
        try:
            candidate = (root / Path(*relative_root.split("/"))).resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise PluginLoadError(
                f"trusted root {relative_root!r} cannot be resolved: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not _is_relative_to(candidate, root):
            raise PluginLoadError(
                f"trusted root {relative_root!r} resolves outside project_root"
            )
        if not candidate.is_dir():
            raise PluginLoadError(f"trusted root {relative_root!r} is not a directory")
        resolved.append(candidate)
    return tuple(resolved)


class PluginLoader:
    def __init__(
        self,
        policy: PluginPolicy,
        domain_registry: DomainRegistry,
        *,
        project_root: str | Path,
    ) -> None:
        if not isinstance(policy, PluginPolicy):
            raise PluginLoadError("policy must be a PluginPolicy")
        if not isinstance(domain_registry, DomainRegistry):
            raise PluginLoadError("domain_registry must be a DomainRegistry")
        self._policy = policy
        self._domains = domain_registry
        try:
            self._project_root = Path(project_root).resolve(strict=True)
        except (OSError, TypeError, ValueError) as exc:
            raise PluginLoadError(
                f"project_root cannot be resolved: {type(exc).__name__}: {exc}"
            ) from exc
        self._trusted_roots = resolve_trusted_roots(project_root, policy)

    def load_manifest(self, module_name: str) -> PluginManifest:
        if not self._policy.enabled:
            raise PluginLoadError("plugin policy is disabled")
        try:
            module = validate_module_name(module_name)
            validate_module_allowed(module, self._policy)
            loaded = resolve_module(
                module,
                project_root=self._project_root,
                trusted_roots=self._trusted_roots,
            )
            try:
                factory = getattr(loaded, "get_plugin_manifest")
            except AttributeError as exc:
                raise PluginValidationError(
                    "module does not export get_plugin_manifest"
                ) from exc
            if not callable(factory):
                raise PluginValidationError("get_plugin_manifest must be callable")
            manifest = factory()
            validate_plugin_manifest(manifest)
            if manifest.name not in self._policy.allowed_plugins:
                raise PluginValidationError(
                    f"plugin {manifest.name!r} is not in allowed_plugins"
                )
            validate_manifest_domains(manifest, self._domains)
            return manifest
        except PluginLoadError:
            raise
        except ModuleResolutionError as exc:
            raise PluginLoadError(
                f"Failed to load plugin module {module_name!r}: {exc}"
            ) from exc
        except Exception as exc:
            raise PluginLoadError(
                f"Failed to load plugin module {module_name!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def load(self, module_name: str) -> PluginManifest:
        """Compatibility alias for the manifest-only loading contract."""

        return self.load_manifest(module_name)


def load_plugin(
    module_name: str,
    policy: PluginPolicy,
    domain_registry: DomainRegistry,
    *,
    project_root: str | Path,
) -> PluginManifest:
    return PluginLoader(
        policy,
        domain_registry,
        project_root=project_root,
    ).load_manifest(module_name)


load_plugin_module = load_plugin


__all__ = [
    "PluginLoadError",
    "PluginLoader",
    "load_plugin",
    "load_plugin_module",
    "resolve_trusted_roots",
]
