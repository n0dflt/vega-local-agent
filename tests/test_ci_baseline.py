from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_is_cross_platform_versioned_and_least_privilege() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "pull_request:" in workflow
    assert "branches:\n      - main" in workflow
    assert "contents: read" in workflow
    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    for version in ('"3.12"', '"3.13"', '"3.14"'):
        assert version in workflow
    assert "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5" in workflow
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in workflow
    assert "persist-credentials: false" in workflow
    assert "secrets." not in workflow


def test_ci_covers_the_release_gate_without_publication() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    for expected in (
        "compileall",
        "pytest",
        "check_identity.py",
        "check_policy_consistency.py",
        "smoke_test.py",
        "check_repository_hygiene.py",
        "run_release_check.py",
    ):
        assert expected in workflow
    for forbidden in ("git push", "gh release", "git tag", "git commit"):
        assert forbidden not in workflow


def test_clean_checkout_contains_temp_parent_and_ci_documentation() -> None:
    assert (ROOT / ".tmp" / ".gitkeep").is_file()
    documentation = (ROOT / "docs" / "ci.md").read_text(encoding="utf-8")
    assert "Python 3.12, 3.13" in documentation
    assert "immutable" in documentation
    assert "symlink" in documentation
