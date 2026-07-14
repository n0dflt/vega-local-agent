from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core.production_snapshot import build_production_snapshot
from scripts.vega_banner import VERSION as BANNER_VERSION
from scripts.version import VERSION


ROOT = Path(__file__).resolve().parents[1]


def test_release_identity_is_synchronized() -> None:
    assert VERSION == "v2.13.0"
    assert BANNER_VERSION == VERSION

    for relative in (
        "README.md",
        "CHANGELOG.md",
        "RELEASE_NOTES.md",
        "docs/architecture.md",
        "docs/commands.md",
        "docs/security.md",
        "docs/roadmap.md",
        "docs/v2.13-architecture.md",
        "docs/releases/v2.13.0.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "v2.13.0" in text, relative


def test_required_architecture_and_release_notes_exist() -> None:
    policy = json.loads(
        (ROOT / "config" / "release_policy.json").read_text(encoding="utf-8")
    )

    assert "docs/releases/v2.13.0.md" in policy["required_files"]
    assert "docs/v2.13-architecture.md" in policy["required_files"]
    assert "config/diagnostics_policy.json" in policy["required_files"]
    assert (ROOT / "docs" / "v2.13-architecture.md").is_file()
    assert (ROOT / "docs" / "releases" / "v2.13.0.md").is_file()


def test_release_policy_forbids_automatic_publication() -> None:
    policy = json.loads(
        (ROOT / "config" / "release_policy.json").read_text(encoding="utf-8")
    )

    assert policy["schema_version"] == 1
    assert policy["publishing"]
    assert not any(policy["publishing"].values())


def test_release_check_includes_policy_consistency() -> None:
    release_policy = json.loads(
        (ROOT / "config" / "release_policy.json").read_text(encoding="utf-8")
    )
    command_policy = json.loads(
        (ROOT / "config" / "allowed_commands.json").read_text(encoding="utf-8")
    )
    commands = {item["id"]: item for item in command_policy["commands"]}

    assert "policy-consistency" in release_policy["checks"]["commands"]
    assert commands["policy-consistency"]["argv"] == [
        "python",
        "scripts/check_policy_consistency.py",
    ]
    assert commands["tests"]["argv"] == [
        "python",
        "-m",
        "pytest",
        "-q",
        "-rs",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        ".tmp/pytest-release",
        "--tb=short",
    ]
    assert commands["repository-hygiene"]["argv"] == [
        "python",
        "scripts/check_repository_hygiene.py",
    ]
    assert "repository-hygiene" in release_policy["checks"]["commands"]


def test_production_snapshot_has_no_blocking_consistency_issue() -> None:
    report = build_production_snapshot(ROOT).consistency_report

    assert report.fatal_issues == ()
    assert report.degraded_issues == ()


def test_mutable_runtime_state_is_not_tracked() -> None:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--",
            "data/model_profile.json",
            "data/project_state/tasks.json",
            "logs/diagnostics/execution-traces.jsonl",
            "logs/diagnostics/execution-traces.jsonl.1",
            "logs/diagnostics/execution-traces.jsonl.3",
            "logs/diagnostics/reports/doctor-20260714T000000000000Z.json",
            "logs/diagnostics/.trace-state.lock",
            "logs/diagnostics/reports/.report-state.lock",
            "logs/diagnostics/quarantine/corrupt-trace-0000000000000000.jsonl",
            "logs/diagnostics/reports/.doctor-20260714T000000000000Z.json.deadbeef.tmp",
            "data/workflows/active/workflow-00000000000000000000000000000000.json",
            "data/workflows/history/workflow-00000000000000000000000000000000.json",
            "data/workflows/.workflow-state.lock",
            "data/checkpoints/active/checkpoint-00000000000000000000000000000000.json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_release_documents_contain_no_known_mojibake() -> None:
    markers = ("вЂ", "Рџ", "â€", "Ã")

    for relative in (
        "README.md",
        "CHANGELOG.md",
        "RELEASE_NOTES.md",
        "docs/architecture.md",
        "docs/roadmap.md",
        "docs/v2.13-architecture.md",
        "docs/releases/v2.13.0.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert all(marker not in text for marker in markers), relative
