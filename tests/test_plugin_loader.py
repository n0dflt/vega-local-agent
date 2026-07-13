from types import ModuleType

import pytest

from domains.builtin import build_builtin_domain_registry
import plugins.loader as loader_module
from plugins.loader import PluginLoadError, PluginLoader
from plugins.models import PluginManifest, PluginTool
from plugins.policy import parse_plugin_policy


MODULE = "trusted.plugins.sample"


def manifest(*, name="sample", domain="coding"):
    return PluginManifest(name, "1.0.0", "Sample plugin.", (domain,),
                          (PluginTool("plugin_echo", lambda: "ok", domain, "READ",
                                      ("project.read",), "Echo safely."),))


def policy(**changes):
    data = dict(schema_version=1, enabled=True, fail_closed=True,
                allowed_modules=[MODULE], allowed_plugins=["sample"],
                allowed_package_prefixes=["trusted.plugins"], allow_file_paths=False,
                trusted_roots=["trusted"], allow_entry_points=False, max_plugins=4)
    data.update(changes)
    return parse_plugin_policy(data)


def module_with(factory=...):
    module = ModuleType(MODULE)
    if factory is not ...:
        module.get_plugin_manifest = factory
    return module


def loader(tmp_path, test_policy, resolved, module=None, monkeypatch=None):
    (tmp_path / "trusted").mkdir(exist_ok=True)
    loaded = module or module_with(lambda: manifest())

    def resolve(name, **kwargs):
        resolved.append(name)
        return loaded

    monkeypatch.setattr(loader_module, "resolve_module", resolve)
    return PluginLoader(
        test_policy,
        build_builtin_domain_registry(),
        project_root=tmp_path,
    )


def test_disabled_policy_imports_nothing(tmp_path, monkeypatch):
    resolved = []
    with pytest.raises(PluginLoadError, match="disabled"):
        loader(tmp_path, policy(enabled=False), resolved, monkeypatch=monkeypatch).load_manifest(MODULE)
    assert resolved == []


@pytest.mark.parametrize(
    ("module_name", "changes"),
    [("../plugin.py", {}), ("trusted.plugins.other", {}),
     (MODULE, {"allowed_modules": ["trusted.plugins.other"]}),
     (MODULE, {"allowed_package_prefixes": ["other"]})],
)
def test_module_boundary_rejections(tmp_path, monkeypatch, module_name, changes):
    with pytest.raises(PluginLoadError):
        loader(tmp_path, policy(**changes), [], monkeypatch=monkeypatch).load_manifest(module_name)


@pytest.mark.parametrize(
    "factory",
    [None, 42, lambda: object(), lambda: manifest(name="other"),
     lambda: manifest(domain="unknown")],
)
def test_factory_manifest_and_domain_rejections(tmp_path, monkeypatch, factory):
    subject = loader(
        tmp_path, policy(), [], module_with(factory), monkeypatch,
    )
    with pytest.raises(PluginLoadError):
        subject.load_manifest(MODULE)


def test_success_and_factory_error_preserve_original_type(tmp_path, monkeypatch):
    good = loader(tmp_path, policy(), [], monkeypatch=monkeypatch)
    assert good.load_manifest(MODULE).name == "sample"
    bad = loader(
        tmp_path,
        policy(),
        [],
        module_with(lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
        monkeypatch,
    )
    with pytest.raises(PluginLoadError, match="RuntimeError"):
        bad.load_manifest(MODULE)
