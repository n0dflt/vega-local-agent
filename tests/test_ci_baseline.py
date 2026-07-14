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
    assert "actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd" in workflow
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in workflow
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
    matrix_job, release_job = workflow.split("  release-gate:", maxsplit=1)
    assert "ref: ${{ github.head_ref || github.ref }}" not in matrix_job
    assert "ref: ${{ github.head_ref || github.ref }}" in release_job


def test_clean_checkout_contains_temp_parent_and_ci_documentation() -> None:
    assert (ROOT / ".tmp" / ".gitkeep").is_file()
    documentation = (ROOT / "docs" / "ci.md").read_text(encoding="utf-8")
    assert "Python 3.12, 3.13" in documentation
    assert "immutable" in documentation
    assert "symlink" in documentation


def test_release_check_entrypoint_bootstraps_repository_imports() -> None:
    entrypoint = (ROOT / "scripts" / "run_release_check.py").read_text(
        encoding="utf-8"
    )
    bootstrap = entrypoint.index("sys.path.insert")
    tools_import = entrypoint.index("from tools.release_tools import")
    assert bootstrap < tools_import
    assert '"issues": status.get("issues", [])' in entrypoint
