from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.model_router import (
    enable_auto_selection,
    get_selection_mode,
    set_current_profile,
)
from core.model_selection import ModelSelectionMode


ROOT = Path(__file__).resolve().parents[1]


def test_mutable_runtime_state_is_ignored_and_untracked() -> None:
    ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "data/model_profile.json" in ignore_text
    assert "data/project_state/tasks.json" in ignore_text
    assert "data/project_state/journal.jsonl" in ignore_text


def test_profile_write_is_atomic_and_leaves_no_temporary_state(
    tmp_path: Path,
) -> None:
    profile = set_current_profile(tmp_path, "docs")
    path = tmp_path / "data" / "model_profile.json"

    assert profile["name"] == "docs"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "current_profile": "docs",
        "selection_mode": "manual",
    }
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_failed_atomic_replace_preserves_previous_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    set_current_profile(tmp_path, "code")
    path = tmp_path / "data" / "model_profile.json"
    previous = path.read_bytes()

    def fail_replace(source, destination) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        set_current_profile(tmp_path, "docs")

    assert path.read_bytes() == previous
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_corrupt_profile_state_is_request_local_and_rewritten_on_selection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data" / "model_profile.json"
    path.parent.mkdir(parents=True)
    path.write_text("{corrupt", encoding="utf-8")

    assert get_selection_mode(tmp_path) is ModelSelectionMode.AUTO
    assert path.read_text(encoding="utf-8") == "{corrupt"

    enable_auto_selection(tmp_path)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "current_profile": "code",
        "selection_mode": "auto",
    }
