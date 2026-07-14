#!/usr/bin/env python3
"""Dependency-free release check for the production policy snapshot."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.production_snapshot import build_production_snapshot


def main() -> int:
    snapshot = build_production_snapshot(PROJECT_ROOT)
    report = snapshot.consistency_report

    if report.fatal_issues or report.degraded_issues:
        print(f"FAIL: production policy consistency ({report.summary})")
        for issue in (*report.fatal_issues, *report.degraded_issues):
            print(f"- {issue.severity.value}:{issue.code.value}:{issue.subject}")
        return 1

    print(f"PASS: production policy consistency ({report.summary})")
    for issue in report.warnings:
        print(f"- warning:{issue.code.value}:{issue.subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
