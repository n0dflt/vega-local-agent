from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


DEFAULT_PROFILE = "code"
PROFILE_PATH = Path("data") / "model_profile.json"
MODEL_PROFILES = {
    "fast": {
        "model": "qwen2.5-coder:7b",
        "purpose": "fast responses",
    },
    "code": {
        "model": "qwen2.5-coder:14b",
        "purpose": "code and refactoring",
    },
    "docs": {
        "model": "qwen2.5-coder:14b",
        "purpose": "documents and RAG",
    },
    "deep": {
        "model": "qwen2.5-coder:32b",
        "purpose": "complex architecture and deep analysis",
    },
}


def get_model_profiles() -> dict:
    return MODEL_PROFILES.copy()


def _profile_path(project_root: Path) -> Path:
    return project_root / PROFILE_PATH


def _load_profile_state(project_root: Path) -> tuple[str, str]:
    """Load profile state while preserving the legacy-file migration rule."""

    path = _profile_path(project_root)
    if not path.exists():
        return DEFAULT_PROFILE, "auto"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_PROFILE, "auto"

    if not isinstance(data, dict):
        return DEFAULT_PROFILE, "auto"

    candidate = data.get("current_profile", DEFAULT_PROFILE)
    profile_name = (
        candidate if candidate in MODEL_PROFILES else DEFAULT_PROFILE
    )

    # A valid v2.8 state file represented an explicit user choice.
    if "selection_mode" not in data:
        return profile_name, "manual"

    mode = data["selection_mode"]
    if mode not in {"auto", "manual"}:
        mode = "auto"
    return profile_name, mode


def _write_profile_state(
    project_root: Path,
    profile_name: str,
    selection_mode: str,
) -> None:
    path = _profile_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "current_profile": profile_name,
            "selection_mode": selection_mode,
        },
        ensure_ascii=False,
        indent=2,
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(payload)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def get_current_profile(project_root: Path) -> dict:
    profile_name, _ = _load_profile_state(project_root)

    profile = MODEL_PROFILES[profile_name].copy()
    profile["name"] = profile_name
    return profile


def set_current_profile(project_root: Path, profile_name: str) -> dict:
    profile_name = profile_name.strip().lower()
    if profile_name not in MODEL_PROFILES:
        raise ValueError(f"Unknown model profile: {profile_name}")

    _write_profile_state(
        project_root,
        profile_name,
        "manual",
    )

    profile = MODEL_PROFILES[profile_name].copy()
    profile["name"] = profile_name
    return profile


def enable_auto_selection(project_root: Path) -> dict:
    """Enable automatic selection without changing the stored fallback."""

    profile_name, _ = _load_profile_state(project_root)
    _write_profile_state(
        project_root,
        profile_name,
        "auto",
    )
    profile = MODEL_PROFILES[profile_name].copy()
    profile["name"] = profile_name
    return profile


def get_selection_mode(project_root: Path):
    from core.model_selection import ModelSelectionMode

    return ModelSelectionMode(_load_profile_state(project_root)[1])


def resolve_model(profile_name: str | None = None) -> str:
    name = (profile_name or DEFAULT_PROFILE).strip().lower()
    if name not in MODEL_PROFILES:
        name = DEFAULT_PROFILE
    return MODEL_PROFILES[name]["model"]


def is_ollama_available() -> bool:
    return shutil.which("ollama") is not None


def get_installed_ollama_models() -> list[str]:
    if not is_ollama_available():
        return []

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    models: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        name = stripped.split()[0]
        if name and name != "NAME":
            models.append(name)

    return models


def is_model_installed(model_name: str) -> bool:
    return model_name in get_installed_ollama_models()


def get_model_install_command(model_name: str) -> str:
    return f"ollama pull {model_name}"


def get_model_status(project_root: Path) -> dict:
    profile = get_current_profile(project_root)
    selection_mode = get_selection_mode(project_root)
    model = profile["model"]
    ollama_available = is_ollama_available()
    installed_models = get_installed_ollama_models() if ollama_available else []

    return {
        "current_profile": profile["name"],
        "current_model": model,
        "selection_mode": selection_mode.value,
        "ollama_available": ollama_available,
        "model_installed": model in installed_models,
        "install_command": get_model_install_command(model),
    }
