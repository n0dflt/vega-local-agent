"""Process entrypoint for the built-in read-only Release Manager gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.release_tools import run_release_check


def main() -> int:
    result = run_release_check(Path.cwd())
    data = result.get("data") or {}
    status = data.get("status") or {}
    summary = {
        "ok": result.get("ok") is True,
        "passed": data.get("passed") is True,
        "publish_ready": data.get("publish_ready") is True,
        "branch": status.get("branch"),
        "preparation_ready": status.get("preparation_ready") is True,
        "issues": status.get("issues", []),
        "commands": data.get("commands", []),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] and summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
