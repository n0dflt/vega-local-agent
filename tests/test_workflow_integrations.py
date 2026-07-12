import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from core.confirmation_manager import ConfirmationManager
from workflows import WorkflowEngine,default_registry
from workflows.integrations import PatchToolsAdapter
from workflows.models import WorkflowError,WorkflowStatus

class Verifier:
    def __init__(self): self.runs=0
    def run_once(self,run): self.runs+=1; return {"ok":True,"runs":self.runs,"checks":["integration"]}

class ProductionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
        (self.root/"sample.txt").write_text("before\n",encoding="utf-8")
        self.root_patches=[patch("core.safety.get_project_root",return_value=self.root),patch("tools.patch_tools.get_project_root",return_value=self.root)]
        for item in self.root_patches: item.start(); self.addCleanup(item.stop)
    def test_start_without_patch_waits_for_patch(self):
        engine=WorkflowEngine(self.root,default_registry(),patch_tools=PatchToolsAdapter(),test_tools=Verifier())
        run=engine.start("feature","Implement export")
        self.assertEqual(run.status,WorkflowStatus.WAITING_PATCH)
        self.assertEqual((self.root/"sample.txt").read_text(encoding="utf-8"),"before\n")
    def test_attach_real_pending_patch_does_not_apply_it(self):
        from tools.patch_tools import propose_patch
        proposal=propose_patch("sample.txt","after\n","workflow integration")
        patch_id=proposal["data"]["patch_id"]
        engine=WorkflowEngine(self.root,default_registry(),patch_tools=PatchToolsAdapter(),test_tools=Verifier())
        engine.start("feature","Implement export")
        attached=engine.attach_patch(patch_id)
        self.assertEqual(attached.status,WorkflowStatus.WAITING_CONFIRMATION)
        self.assertEqual((self.root/"sample.txt").read_text(encoding="utf-8"),"before\n")
    def test_attach_rejects_unknown_and_applied_patch(self):
        from tools.patch_tools import apply_patch,propose_patch
        engine=WorkflowEngine(self.root,default_registry(),patch_tools=PatchToolsAdapter(),test_tools=Verifier())
        engine.start("feature","Implement export")
        with self.assertRaises(WorkflowError): engine.attach_patch("missing-patch")
        proposal=propose_patch("sample.txt","after\n","workflow integration"); patch_id=proposal["data"]["patch_id"]
        self.assertTrue(apply_patch(patch_id,confirmed=True)["ok"])
        with self.assertRaises(WorkflowError): engine.attach_patch(patch_id)
    def test_real_pending_patch_is_applied_exactly_once(self):
        from tools.patch_tools import propose_patch
        proposal=propose_patch("sample.txt","after\n","workflow integration")
        self.assertTrue(proposal["ok"]); patch_id=proposal["data"]["patch_id"]
        verifier=Verifier(); engine=WorkflowEngine(self.root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=PatchToolsAdapter(),test_tools=verifier)
        waiting=engine.start("feature","Implement export",patch_id=patch_id)
        self.assertEqual(waiting.status,WorkflowStatus.WAITING_CONFIRMATION)
        completed=engine.confirm()
        self.assertEqual(completed.status,WorkflowStatus.COMPLETED); self.assertEqual((self.root/"sample.txt").read_text(encoding="utf-8"),"after\n")
        self.assertEqual(verifier.runs,1); self.assertIn("sample.txt",completed.report)
        with self.assertRaises(Exception): engine.confirm()
        self.assertEqual((self.root/"sample.txt").read_text(encoding="utf-8"),"after\n")
    def test_legacy_patch_shortcut_remains_confirmation_gated(self):
        from tools.patch_tools import propose_patch
        proposal=propose_patch("sample.txt","after\n","legacy shortcut"); patch_id=proposal["data"]["patch_id"]
        engine=WorkflowEngine(self.root,default_registry(),patch_tools=PatchToolsAdapter(),test_tools=Verifier())
        run=engine.start("feature","Implement export",patch_id=patch_id)
        self.assertEqual(run.status,WorkflowStatus.WAITING_CONFIRMATION)
        self.assertEqual((self.root/"sample.txt").read_text(encoding="utf-8"),"before\n")

if __name__=="__main__": unittest.main()
