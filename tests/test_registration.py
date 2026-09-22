"""Contract tests: what plugin.yaml declares vs what register() actually does.

This is the same ground `hermes plugins doctor` covers, kept in-process so a
drift between the manifest and the code fails here first.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_plugin_package():
    """Import the plugin directory the way Hermes does — by path, not by name."""
    spec = importlib.util.spec_from_file_location(
        "gonogo_plugin_under_test", ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeContext:
    """Records registrations. Mirrors the PluginContext surface this plugin uses."""

    def __init__(self):
        self.tools: dict[str, dict] = {}
        self.skills: dict[str, Path] = {}
        self.hooks: dict[str, list] = {}

    def register_tool(self, name, toolset=None, schema=None, handler=None, **_):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def register_skill(self, name, path, **_):
        self.skills[name] = Path(path)

    def register_hook(self, name, callback, **_):
        self.hooks.setdefault(name, []).append(callback)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ctx() -> FakeContext:
    module = load_plugin_package()
    context = FakeContext()
    module.register(context)          # must not raise — Hermes disables the plugin if it does
    return context


def test_registers_exactly_what_the_manifest_declares(manifest, ctx):
    assert sorted(ctx.tools) == sorted(manifest["provides_tools"])
    assert sorted(ctx.hooks) == sorted(manifest["provides_hooks"])


def test_manifest_is_manifest_v2(manifest):
    assert manifest["name"] == "gonogo"
    assert manifest["manifest_version"] == 2
    assert isinstance(manifest["api_version"], int)
    assert manifest["license"] == "MIT"
    assert manifest["homepage"].startswith("https://")
    assert manifest["version"] == "0.1.0"


def test_dependency_range_agrees_with_the_manifest_version():
    """One declared dependency, in the file Hermes prefers (pyproject.toml)."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "gonogo-eval>=0.2,<0.3" in text


def test_every_tool_has_a_schema_whose_name_matches(ctx):
    for name, entry in ctx.tools.items():
        assert entry["schema"]["name"] == name
        assert entry["schema"]["description"].strip()
        assert entry["schema"]["parameters"]["type"] == "object"
        assert callable(entry["handler"])


def test_tool_descriptions_say_when_to_use_them(ctx):
    """The description is the only thing the model sees — it has to route on it."""
    for name, entry in ctx.tools.items():
        description = entry["schema"]["description"].lower()
        assert "when" in description, f"{name} never says when to use it"
        assert len(description) > 200, f"{name}'s description is too thin to route on"


def test_all_tools_share_the_gonogo_toolset(ctx):
    assert {entry["toolset"] for entry in ctx.tools.values()} == {"gonogo"}


def test_bundled_skill_is_registered_and_present(ctx):
    assert "gonogo-verdict" in ctx.skills
    skill_file = ctx.skills["gonogo-verdict"]
    assert skill_file.is_file()
    text = skill_file.read_text(encoding="utf-8")
    assert text.startswith("---")           # frontmatter, or the loader ignores it
    assert "name: gonogo-verdict" in text


def test_plugin_registers_no_hooks_or_network_surface(manifest, ctx):
    """No hooks, no env vars, no capabilities — the whole blast radius is three tools."""
    assert ctx.hooks == {}
    assert manifest.get("requires_env") in (None, [])
    assert manifest.get("capabilities") in (None, [])