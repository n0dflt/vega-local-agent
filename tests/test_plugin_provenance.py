from types import ModuleType

import pytest

from domains.builtin import build_builtin_domain_registry
import plugins.loader as loader_module
from plugins.loader import PluginLoadError, PluginLoader
from plugins.models import PluginManifest
from plugins.module_resolver import ModuleResolutionError
from plugins.policy import parse_plugin_policy


MODULE = "trusted.plugins.sample"


def policy(**changes):
    data = dict(
        schema_version=1, enabled=True, fail_closed=True,
        allowed_modules=[MODULE], allowed_plugins=["sample"],
        allowed_package_prefixes=["trusted.plugins"], trusted_roots=["trusted"],
        allow_file_paths=False, allow_entry_points=False, max_plugins=4,
    )
    data.update(changes)
    return parse_plugin_policy(data)


def manifest():
    return PluginManifest("sample", "1.0.0", "Sample plugin.", ("coding",), ())


def subject(tmp_path):
    (tmp_path / "trusted").mkdir(exist_ok=True)
    return PluginLoader(
        policy(), build_builtin_domain_registry(), project_root=tmp_path,
    )


def test_loader_delegates_to_trusted_root_scoped_resolver(tmp_path, monkeypatch):
    loaded = ModuleType(MODULE)
    loaded.get_plugin_manifest = manifest
    calls = []

    def resolve(name, *, project_root, trusted_roots):
        calls.append((name, project_root, trusted_roots))
        return loaded

    monkeypatch.setattr(loader_module, "resolve_module", resolve)
    assert subject(tmp_path).load_manifest(MODULE).name == "sample"
    assert calls == [(
        MODULE,
        tmp_path.resolve(),
        ((tmp_path / "trusted").resolve(),),
    )]


def test_resolver_failure_is_preserved_as_plugin_load_error(tmp_path, monkeypatch):
    def reject(*args, **kwargs):
        raise ModuleResolutionError("outside trusted roots")

    monkeypatch.setattr(loader_module, "resolve_module", reject)
    with pytest.raises(PluginLoadError, match="outside trusted roots") as caught:
        subject(tmp_path).load_manifest(MODULE)
    assert isinstance(caught.value.__cause__, ModuleResolutionError)


def test_trusted_root_must_be_existing_directory(tmp_path):
    trusted_file = tmp_path / "trusted"
    trusted_file.write_text("not a directory", encoding="utf-8")
    with pytest.raises(PluginLoadError, match="not a directory"):
        PluginLoader(
            policy(), build_builtin_domain_registry(), project_root=tmp_path,
        )
