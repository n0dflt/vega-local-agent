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

    def prepare_safe(self, patch_id: str) -> dict:
        """Return only the fixed metadata needed for confirmation binding."""
        from tools.patch_tools import show_patch

        result = show_patch(patch_id)
        data = result.get("data")
        required = {
            "patch_id", "status", "target_path", "original_sha256", "proposed_sha256"
        }
        if (
            not result.get("ok")
            or not isinstance(data, dict)
            or not required.issubset(data)
            or data.get("patch_id") != patch_id
            or data.get("status") not in {"pending", "applied", "rolled_back"}
        ):
            raise WorkflowError("managed_patch_invalid")
        return {key: data[key] for key in required}

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

    def rollback(self, patch_id, confirmed: bool = False) -> dict:
        from tools.patch_tools import rollback_patch

        result = rollback_patch(patch_id, confirmed=confirmed)
        data = result.get("data")
        if not result.get("ok") or not isinstance(data, dict) or data.get("status") != "rolled_back":
            raise WorkflowError("rollback_refused")
        return {
            "patch_id": data.get("patch_id"),
            "target_path": data.get("target_path"),
            "status": data.get("status"),
        }


class TestToolsAdapter:
    """Run one controlled test group for the current workflow iteration."""

    __test__ = False

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def run_once(self, run) -> dict:
        del run
        try:
            from tools.test_tools import run_test_group
        except ImportError as exc:
            raise WorkflowError(f"Test Tools are unavailable: {exc}") from exc

        result = run_test_group("all", self.project_root)
        if not isinstance(result, dict):
            raise WorkflowError(
                "Test Tools returned an invalid result."
            )
        if not result.get("ok") and result.get("data") is None:
            raise WorkflowError(
                result.get("error")
                or "Test Tools could not start verification."
            )
        return {
            "ok": bool(result.get("ok")),
            "error": result.get("error"),
            "data": result.get("data"),
            "runs": 1,
            "group": "all",
        }

    def resolve(self, group_id: str) -> dict:
        from tools.test_tools import list_test_groups

        result = list_test_groups(self.project_root)
        if not result.get("ok") or not isinstance(result.get("data"), list):
            raise WorkflowError("test_configuration_missing")
        match = next((item for item in result["data"] if item.get("id") == group_id), None)
        if not match or not match.get("available") or not match.get("enabled"):
            raise WorkflowError("test_configuration_missing")
        return {"group_id": match["id"], "command_id": match["command_id"]}

    def run_group(self, group_id: str) -> dict:
        from tools.test_tools import run_test_group

        result = run_test_group(group_id, self.project_root)
        data = result.get("data")
        if not isinstance(data, dict):
            return {
                "passed": False,
                "returncode": None,
                "timed_out": False,
                "duration_ms": 0,
                "outcome_code": "not_started",
            }
        passed = result.get("ok") is True and data.get("returncode") == 0
        timed_out = data.get("timed_out") is True
        return {
            "passed": passed,
            "returncode": data.get("returncode") if type(data.get("returncode")) is int else None,
            "timed_out": timed_out,
            "duration_ms": min(data.get("duration_ms", 0), 3_600_000)
            if type(data.get("duration_ms")) is int
            else 0,
            "outcome_code": "passed" if passed else "timed_out" if timed_out else "failed",
        }


class ReviewToolsAdapter:
    """Run the isolated review pipeline without exposing write tools."""
    def __init__(self,project_root:Path,provider=None):
        from review.review_pipeline import ReviewPipeline
        self.pipeline=ReviewPipeline(project_root,provider)

    def run_once(self,run)->dict:
        return self.pipeline.run(run).to_dict()
