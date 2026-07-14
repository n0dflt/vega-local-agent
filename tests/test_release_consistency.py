from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core.production_snapshot import build_production_snapshot
from scripts.vega_banner import VERSION as BANNER_VERSION, VegaStatus, render_banner
from scripts.version import VERSION
from tools.release_tools import build_release_notes


ROOT = Path(__file__).resolve().parents[1]


def test_release_identity_is_synchronized() -> None:
    assert VERSION == "v3.0.0"
    assert BANNER_VERSION == VERSION

    for relative in (
        "README.md",
        "CHANGELOG.md",
        "RELEASE_NOTES.md",
        "docs/architecture.md",
        "docs/commands.md",
        "docs/security.md",
        "docs/roadmap.md",
        "docs/v3.0-architecture.md",
        "docs/migrations/v3.0.0.md",
        "docs/releases/v3.0.0.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "v3.0.0" in text, relative


def test_required_architecture_and_release_notes_exist() -> None:
    policy = json.loads(
        (ROOT / "config" / "release_policy.json").read_text(encoding="utf-8")
    )

    assert "docs/releases/v3.0.0.md" in policy["required_files"]
    assert "docs/migrations/v3.0.0.md" in policy["required_files"]
    assert "docs/v3.0-architecture.md" in policy["required_files"]
    assert "config/diagnostics_policy.json" in policy["required_files"]
    assert (ROOT / "docs" / "v3.0-architecture.md").is_file()
    assert (ROOT / "docs" / "migrations" / "v3.0.0.md").is_file()
    assert (ROOT / "docs" / "releases" / "v3.0.0.md").is_file()


def test_legacy_config_and_release_notes_use_v3_identity() -> None:
    config = (ROOT / "config" / "vega.config.yaml").read_text(encoding="utf-8")
    policy = json.loads(
        (ROOT / "config" / "release_policy.json").read_text(encoding="utf-8")
    )
    notes = build_release_notes(ROOT)

    assert 'version: "3.0.0"' in config
    assert 'current_version: "v3.0.0"' in config
    assert all("v2.13" not in path for path in policy["required_files"])
    assert notes["ok"]
    assert notes["data"]["version"] == VERSION
    assert "## v3.0.0 - Operator Console" in notes["data"]["draft"]
    assert "## v2.13.0" not in notes["data"]["draft"]


def test_legacy_banner_status_constructor_remains_source_compatible() -> None:
    output = render_banner(VegaStatus("legacy-model", True, VERSION))

    assert "legacy-model" in output
    assert "Internet" not in output


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
        ".tmp/pytest-release-{run_id}",
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
        "docs/v3.0-architecture.md",
        "docs/migrations/v3.0.0.md",
        "docs/releases/v3.0.0.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert all(marker not in text for marker in markers), relative
