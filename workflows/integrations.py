"""Fail-closed adapters for existing VEGA Patch Tools and Test Tools."""

from __future__ import annotations

from pathlib import Path

from workflows.models import WorkflowError


class PatchToolsAdapter:
    """Validate, apply, and inspect real Patch Tools artifacts."""

    def prepare(self, run) -> dict:
        candidate = run.artifacts.get("requested_patch_id")
        if not candidate:
            raise WorkflowError(
                "A real pending Patch Tools patch_id is required."
            )

        from tools.patch_tools import show_patch

        result = show_patch(candidate)
        data = result.get("data")
        if not result.get("ok") or not isinstance(data, dict):
            raise WorkflowError(
                result.get("error") or "Pending patch could not be loaded."
            )
        if data.get("status") != "pending":
            raise WorkflowError("Workflow requires a pending patch artifact.")
        if data.get("patch_id") != candidate:
            raise WorkflowError("Patch Tools returned a mismatched patch ID.")
        return {
            "patch_id": candidate,
            "status": "pending",
            "target_path": data.get("target_path"),
            "diff": data.get("diff"),
        }

    def apply(self, patch_id, confirmed: bool = False) -> dict:
        if not patch_id:
            raise WorkflowError(
                "Patch application requires a real patch_id."
            )

        from tools.patch_tools import apply_patch

        result = apply_patch(patch_id, confirmed=confirmed)
        data = result.get("data")
        applied = (
            result.get("ok")
            and isinstance(data, dict)
            and data.get("status") == "applied"
        )
        if not applied:
            raise WorkflowError(result.get("error") or "Patch was not applied.")
        return result

    def inspect(self, patch_id) -> dict:
        if not patch_id:
            raise WorkflowError("Patch inspection requires a real patch_id.")

        from tools.patch_tools import show_patch

        result = show_patch(patch_id)
        if not result.get("ok") or not isinstance(result.get("data"), dict):
            raise WorkflowError(
                result.get("error") or "Patch state is unavailable."
            )
        return result["data"]


class TestToolsAdapter:
    """Run the existing controlled test group exactly once."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def run_once(self, run) -> dict:
        del run
        try:
            from tools.test_tools import run_test_group
        except ImportError as exc:
            raise WorkflowError(f"Test Tools are unavailable: {exc}") from exc

        result = run_test_group("all", self.project_root)
        if not isinstance(result, dict) or not result.get("ok"):
            raise WorkflowError(
                (result or {}).get("error")
                or "Test Tools verification failed."
            )
        return {
            "ok": True,
            "error": None,
            "data": result.get("data"),
            "runs": 1,
            "group": "all",
        }
