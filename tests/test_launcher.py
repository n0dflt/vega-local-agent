from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "vega.cmd"


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows launcher test",
)


def _cmd() -> str:
    return os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")


def test_launcher_uses_explicit_runtime_without_python_on_path() -> None:
    environment = os.environ.copy()
    environment["VEGA_PYTHON"] = sys.executable
    environment["PATH"] = ""
    environment.pop("VIRTUAL_ENV", None)

    completed = subprocess.run(
        [_cmd(), "/d", "/c", str(LAUNCHER)],
        cwd=ROOT,
        input="/exit\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        env=environment,
    )

    assert completed.returncode == 0
    assert "VEGA / OPERATOR CONSOLE" in completed.stdout
    assert "Bye." in completed.stdout


def test_launcher_fails_clearly_when_no_runtime_is_available() -> None:
    environment = os.environ.copy()
    environment["PATH"] = ""
    environment.pop("VEGA_PYTHON", None)
    environment.pop("VIRTUAL_ENV", None)

    completed = subprocess.run(
        [_cmd(), "/d", "/c", str(LAUNCHER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
        env=environment,
    )

    assert completed.returncode == 1
    assert "VEGA could not find Python" in completed.stderr


def test_launcher_does_not_make_tmp_a_runtime_contract() -> None:
    content = LAUNCHER.read_text(encoding="utf-8-sig").lower()

    assert ".tmp" not in content
    assert "vega_python" in content
    assert "virtual_env" in content
    assert "py -3" in content
