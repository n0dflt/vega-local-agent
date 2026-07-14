"""Cross-platform release checks for whitespace and generated-state hygiene."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATED_EXACT = frozenset(
    {
        "data/model_profile.json",
        "data/project_state/tasks.json",
        "data/project_state/journal.jsonl",
        "logs/diagnostics/execution-traces.jsonl",
    }
)
GENERATED_PARTS = (
    "logs/diagnostics/reports/",
    "logs/diagnostics/quarantine/",
    "data/index/",
    "data/checkpoints/",
)
GENERATED_NAMES = frozenset({".trace-state.lock", ".report-state.lock", ".workflow-state.lock"})
IGNORE_PROBES = (
    "logs/diagnostics/.trace-state.lock",
    "logs/diagnostics/reports/.report-state.lock",
    "logs/diagnostics/quarantine/corrupt-trace-0000000000000000.jsonl",
    "logs/diagnostics/reports/.doctor-20260714T000000000000Z.json.deadbeef.tmp",
    "data/index/documents_index.json",
    "data/workflows/active/workflow-00000000000000000000000000000000.json",
    "data/workflows/history/.workflow-00000000000000000000000000000000.00000000000000000000000000000000.tmp",
    "data/workflows/.workflow-state.lock",
    "data/checkpoints/active/checkpoint-00000000000000000000000000000000.json",
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _check_result(label: str, result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        print(f"PASS: {label}")
        return True
    print(f"FAIL: {label}")
    return False


def _committed_range() -> tuple[str, ...]:
    base = os.environ.get("GITHUB_BASE_REF", "").strip()
    if base:
        candidate = f"origin/{base}"
        merge_base = _git("merge-base", "HEAD", candidate)
        if merge_base.returncode == 0 and merge_base.stdout.strip():
            return (f"{merge_base.stdout.strip()}..HEAD",)
    before = os.environ.get("GITHUB_EVENT_BEFORE", "").strip()
    if before and before != "0" * 40:
        return (f"{before}..HEAD",)
    parent = _git("rev-parse", "HEAD^")
    if parent.returncode == 0:
        return ("HEAD^..HEAD",)
    return ()


def main() -> int:
    passed = True
    passed &= _check_result("working-tree whitespace", _git("diff", "--check"))
    passed &= _check_result("staged whitespace", _git("diff", "--cached", "--check"))
    committed = _committed_range()
    if committed:
        passed &= _check_result(
            "committed-range whitespace", _git("diff", "--check", *committed)
        )

    tracked_result = _git("ls-files")
    if tracked_result.returncode != 0:
        print("FAIL: generated-state tracking")
        passed = False
    else:
        unsafe = []
        for raw in tracked_result.stdout.splitlines():
            normalized = raw.replace("\\", "/")
            if (
                normalized in GENERATED_EXACT
                or any(normalized.startswith(prefix) for prefix in GENERATED_PARTS)
                or (
                    normalized.startswith(("data/workflows/active/", "data/workflows/history/"))
                    and Path(normalized).suffix in {".json", ".tmp"}
                )
                or Path(normalized).name in GENERATED_NAMES
            ):
                unsafe.append(normalized)
        if unsafe:
            print("FAIL: generated-state tracking")
            passed = False
        else:
            print("PASS: generated-state tracking")

    ignore_rules_passed = all(
        _git("check-ignore", "--quiet", "--", probe).returncode == 0
        for probe in IGNORE_PROBES
    )
    if ignore_rules_passed:
        print("PASS: generated-state ignore rules")
    else:
        print("FAIL: generated-state ignore rules")
        passed = False
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
