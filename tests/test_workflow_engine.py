import json,tempfile,unittest
from pathlib import Path
from core.confirmation_manager import ConfirmationManager
from workflows import WorkflowEngine,default_registry
from workflows.engine import ActiveWorkflowError,WorkflowStorageError
from workflows.models import WorkflowError,WorkflowStatus

class PatchStub:
    def __init__(self): self.applied=0; self.state="pending"
    def prepare(self,run):
        patch_id=run.artifacts.get("requested_patch_id")
        if not patch_id: raise WorkflowError("patch required")
        return {"patch_id":patch_id,"status":"pending","target_path":"sample.py"}
    def apply(self,patch_id,confirmed=False):
        if not confirmed: return {"ok":False,"error":"confirmation required","data":None}
        if self.state=="applied": raise AssertionError("patch applied twice")
        self.applied+=1; self.state="applied"
        return {"ok":True,"error":None,"data":{"patch_id":patch_id,"status":"applied","target_path":"sample.py"}}
    def inspect(self,patch_id): return {"patch_id":patch_id,"status":self.state,"target_path":"sample.py"}

class VerificationStub:
    def __init__(self,ok=True): self.ok=ok; self.runs=0
    def run_once(self,run): self.runs+=1; return {"ok":self.ok,"runs":self.runs,"workflow":run.workflow_type,"error":None if self.ok else "failed"}

class WorkflowEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
        self.confirmations=ConfirmationManager(); self.patch=PatchStub(); self.tests=VerificationStub()
        self.engine=WorkflowEngine(self.root,default_registry(),confirmation_manager=self.confirmations,patch_tools=self.patch,test_tools=self.tests)
    def start(self,kind="feature",task="Implement feature"): return self.engine.start(kind,task,patch_id="patch-1")
    def test_start_without_patch_waits_for_patch(self):
        run=self.engine.start("feature","Implement feature")
        self.assertEqual(run.status,WorkflowStatus.WAITING_PATCH)
        with self.assertRaises(ActiveWorkflowError): self.engine.confirm()
    def test_feature_waits_before_apply(self):
        run=self.start(); self.assertEqual(run.status,WorkflowStatus.WAITING_CONFIRMATION); self.assertEqual(self.patch.applied,0)
        self.assertIn("patch",run.completed_steps); self.assertIn("goal",run.artifacts)
    def test_confirm_applies_once_verifies_and_reports(self):
        self.start("bugfix","Fix parser error"); run=self.engine.confirm()
        self.assertEqual(run.status,WorkflowStatus.COMPLETED); self.assertEqual(self.patch.applied,1); self.assertEqual(self.tests.runs,1)
        self.assertEqual(run.changed_files,["sample.py"]); self.assertIn("Checks: 1",run.report); self.assertIn("probable_cause",run.artifacts)
        self.assertEqual(run.step("reproduction").status.value,"skipped")
        self.assertNotIn("reproduction",run.completed_steps)
        with self.assertRaises(ActiveWorkflowError): self.engine.confirm()
        self.assertEqual(self.patch.applied,1)
    def test_refactor_mixed_feature_scope_fails(self):
        with self.assertRaises(WorkflowError): self.start("refactor","Refactor parser and add new feature")
        self.assertTrue(self.engine.history()[0].artifacts["mixed_scope_detected"])
    def test_refactor_records_behavior_contract(self):
        self.start("refactor","Refactor parser without changing behavior"); run=self.engine.confirm()
        self.assertTrue(run.artifacts["behavior_preservation_required"])
    def test_second_active_is_rejected_and_cancel_archives(self):
        self.start()
        with self.assertRaises(ActiveWorkflowError): self.engine.start("bugfix","Fix error",patch_id="patch-2")
        self.assertEqual(self.engine.cancel().status,WorkflowStatus.CANCELLED)
    def test_resume_waiting_confirmation_after_restart(self):
        run=self.start(); restarted=WorkflowEngine(self.root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=self.patch,test_tools=self.tests)
        self.assertEqual(restarted.resume().workflow_id,run.workflow_id); self.assertTrue(restarted.confirmation_manager.has_pending)
    def test_resume_read_only_states_reaches_confirmation(self):
        for state in (WorkflowStatus.CREATED,WorkflowStatus.ANALYZING,WorkflowStatus.PLANNING):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary); patch=PatchStub(); tests=VerificationStub(); engine=WorkflowEngine(root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=patch,test_tools=tests)
                run=default_registry().get("feature").create_run("Implement export"); run.artifacts["requested_patch_id"]="patch-1"
                if state is not WorkflowStatus.CREATED: run.transition(WorkflowStatus.ANALYZING)
                if state is WorkflowStatus.PLANNING:
                    run.context={"related_files":["core/export.py"]}; run.step("context").start(); run.step("context").complete(run.context); run.transition(WorkflowStatus.PLANNING)
                engine._save(run)
                self.assertEqual(engine.resume().status,WorkflowStatus.WAITING_PATCH)
    def test_resume_waiting_patch_remains_read_only(self):
        run=self.engine.start("feature","Implement export")
        restarted=WorkflowEngine(self.root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=self.patch,test_tools=self.tests)
        restored=restarted.resume()
        self.assertEqual(restored.workflow_id,run.workflow_id)
        self.assertEqual(restored.status,WorkflowStatus.WAITING_PATCH)
        self.assertEqual(self.patch.applied,0)
    def test_resume_executing_does_not_apply_twice(self):
        run=self.start(); self.confirmations.resolve(__import__('core.intent_router',fromlist=['ConfirmationDecision']).ConfirmationDecision.CONFIRM)
        run.step("confirmation").start(); run.step("confirmation").complete({"confirmed":True}); run.transition(WorkflowStatus.EXECUTING)
        apply=run.step("apply"); apply.start(); self.patch.state="applied"; self.engine._save(run)
        recovered=self.engine.resume(); self.assertEqual(recovered.status,WorkflowStatus.COMPLETED); self.assertEqual(self.patch.applied,0)
    def test_resume_verifying_runs_only_when_not_recorded(self):
        self.start(); run=self.engine._require_active(); self.confirmations.resolve(__import__('core.intent_router',fromlist=['ConfirmationDecision']).ConfirmationDecision.CONFIRM)
        run.step("confirmation").start(); run.step("confirmation").complete({}); run.transition(WorkflowStatus.EXECUTING)
        run.step("apply").start(); run.step("apply").complete({"ok":True,"data":{"status":"applied","target_path":"sample.py"}}); run.changed_files=["sample.py"]; run.transition(WorkflowStatus.VERIFYING); self.engine._save(run)
        self.engine.resume(); self.assertEqual(self.tests.runs,1)
    def test_corrupt_active_and_history_json_are_reported(self):
        active=self.root/"data/workflows/active"; (active/"broken.json").write_text("{",encoding="utf-8")
        with self.assertRaises(WorkflowStorageError): self.engine.status()
        (active/"broken.json").unlink(); history=self.root/"data/workflows/history"; (history/"broken.json").write_text("{",encoding="utf-8")
        with self.assertRaises(WorkflowStorageError): self.engine.history()
    def test_workflow_id_path_traversal_rejected(self):
        run=default_registry().get("feature").create_run("Task"); run.workflow_id="../escape"
        with self.assertRaises(ValueError): self.engine._save(run)
    def test_failed_verification_runs_once(self):
        failing=VerificationStub(False); engine=WorkflowEngine(self.root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=self.patch,test_tools=failing)
        engine.start("bugfix","Fix error",patch_id="patch-1")
        with self.assertRaises(WorkflowError): engine.confirm()
        self.assertEqual(failing.runs,1); self.assertTrue(engine.history()[0].manual_intervention_required)
    def test_unrelated_confirmation_is_not_cleared_on_failure(self):
        manager=ConfirmationManager(); manager.request("other","other","Other action")
        engine=WorkflowEngine(self.root,default_registry(),confirmation_manager=manager,patch_tools=self.patch,test_tools=self.tests)
        with self.assertRaises(Exception): engine.start("feature","Implement export",patch_id="patch-1")
        self.assertTrue(manager.has_pending); self.assertEqual(manager.pending.action_id,"other")

    def test_missing_verifier_cannot_complete(self):
        class MissingVerifier:
            def run_once(self,run): raise WorkflowError("Test Tools are unavailable")
        engine=WorkflowEngine(self.root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=self.patch,test_tools=MissingVerifier())
        engine.start("feature","Implement export",patch_id="patch-1")
        with self.assertRaises(WorkflowError): engine.confirm()
        self.assertEqual(engine.history()[0].status,WorkflowStatus.FAILED)
    def test_terminal_active_state_cannot_resume(self):
        run=default_registry().get("feature").create_run("Implement export"); run.status=WorkflowStatus.COMPLETED; self.engine._save(run)
        with self.assertRaises(ActiveWorkflowError): self.engine.resume()
    def test_task_plan_changes_only_after_explicit_link(self):
        from core.task_manager import TaskManager
        manager=TaskManager(self.root)
        task=manager.create_task("User task")
        manager.add_plan(task["id"],["Keep this plan"])
        run=self.engine.start("feature","Implement export")
        self.assertEqual(manager.get_task(task["id"])["plan"],["Keep this plan"])
        linked=self.engine.link_task(task["id"])
        self.assertEqual(linked.linked_task_id,task["id"])
        self.assertEqual(manager.get_task(task["id"])["plan"],run.plan)

if __name__=="__main__": unittest.main()
