import json,shutil,tempfile,unittest
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

class PassReviewTools:
    def run_once(self,run):
        return {"review_id":"review-test","workflow_id":run.workflow_id,"patch_iteration":len(run.test_fix_iterations),"reviewed_patch_ids":[(run.patch or {}).get("patch_id")],"reviewed_files":list(run.changed_files),"findings":[],"blocking_findings":[],"highest_severity":"info","passed":True,"summary":"clean","reviewer_error":"","created_at":"test"}

class LoopPatchStub:
    def __init__(self): self.applied=[]; self.states={}
    def prepare(self,run):
        patch_id=run.artifacts.get("requested_patch_id")
        if not patch_id: raise WorkflowError("patch required")
        self.states.setdefault(patch_id,"pending")
        return {"patch_id":patch_id,"status":"pending","target_path":f"{patch_id}.py"}
    def apply(self,patch_id,confirmed=False):
        if not confirmed: return {"ok":False,"error":"confirmation required","data":None}
        if self.states.get(patch_id)!="pending": raise AssertionError("patch applied twice")
        self.states[patch_id]="applied"; self.applied.append(patch_id)
        return {"ok":True,"error":None,"data":{"patch_id":patch_id,"status":"applied","target_path":f"{patch_id}.py"}}
    def inspect(self,patch_id): return {"patch_id":patch_id,"status":self.states.get(patch_id),"target_path":f"{patch_id}.py"}

class SequenceVerifier:
    def __init__(self,results): self.results=list(results); self.runs=0
    def run_once(self,run):
        del run
        result=self.results[self.runs]; self.runs+=1
        return {"ok":result,"runs":self.runs,"error":None if result else "failed"}

class WorkflowEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
        self.install_policy(self.root)
        self.confirmations=ConfirmationManager(); self.patch=PatchStub(); self.tests=VerificationStub()
        self.engine=WorkflowEngine(self.root,default_registry(),confirmation_manager=self.confirmations,patch_tools=self.patch,test_tools=self.tests,review_tools=PassReviewTools())
    @staticmethod
    def install_policy(root):
        (root/"config").mkdir(parents=True,exist_ok=True)
        shutil.copy(Path(__file__).parents[1]/"config/checkpoint_policy.json",root/"config/checkpoint_policy.json")
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
        run=self.start(); restarted=WorkflowEngine(self.root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=self.patch,test_tools=self.tests,review_tools=PassReviewTools())
        self.assertEqual(restarted.resume().workflow_id,run.workflow_id); self.assertTrue(restarted.confirmation_manager.has_pending)
    def test_resume_read_only_states_reaches_confirmation(self):
        for state in (WorkflowStatus.CREATED,WorkflowStatus.ANALYZING,WorkflowStatus.PLANNING):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary); self.install_policy(root); patch=PatchStub(); tests=VerificationStub(); engine=WorkflowEngine(root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=patch,test_tools=tests,review_tools=PassReviewTools())
                run=default_registry().get("feature").create_run("Implement export"); run.artifacts["requested_patch_id"]="patch-1"
                if state is not WorkflowStatus.CREATED: run.transition(WorkflowStatus.ANALYZING)
                if state is WorkflowStatus.PLANNING:
                    run.context={"related_files":["core/export.py"]}; run.step("context").start(); run.step("context").complete(run.context); run.transition(WorkflowStatus.PLANNING)
                engine._save(run)
                self.assertEqual(engine.resume().status,WorkflowStatus.WAITING_PATCH)
    def test_resume_waiting_patch_remains_read_only(self):
        run=self.engine.start("feature","Implement export")
        restarted=WorkflowEngine(self.root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=self.patch,test_tools=self.tests,review_tools=PassReviewTools())
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
        failing=VerificationStub(False); engine=WorkflowEngine(self.root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=self.patch,test_tools=failing,review_tools=PassReviewTools())
        engine.start("bugfix","Fix error",patch_id="patch-1")
        run=engine.confirm()
        self.assertEqual(failing.runs,1); self.assertEqual(run.status,WorkflowStatus.WAITING_PATCH)
        self.assertEqual(len(run.test_fix_iterations),1)
    def test_failed_test_accepts_a_new_confirmed_fix(self):
        patch=LoopPatchStub(); tests=SequenceVerifier([False,True])
        engine=WorkflowEngine(self.root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=patch,test_tools=tests,review_tools=PassReviewTools())
        engine.start("bugfix","Fix error",patch_id="patch-1")
        waiting=engine.confirm()
        self.assertEqual(waiting.status,WorkflowStatus.WAITING_PATCH)
        engine.attach_patch("patch-2")
        completed=engine.confirm()
        self.assertEqual(completed.status,WorkflowStatus.COMPLETED)
        self.assertEqual(patch.applied,["patch-1","patch-2"])
        self.assertEqual(len(completed.test_fix_iterations),2)
        self.assertEqual(completed.changed_files,["patch-1.py","patch-2.py"])
    def test_fix_limit_fails_closed(self):
        patch=LoopPatchStub(); tests=SequenceVerifier([False,False,False])
        engine=WorkflowEngine(self.root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=patch,test_tools=tests,review_tools=PassReviewTools())
        engine.start("bugfix","Fix error",patch_id="patch-1"); engine.confirm()
        engine.attach_patch("patch-2"); engine.confirm(); engine.attach_patch("patch-3")
        with self.assertRaises(WorkflowError): engine.confirm()
        failed=engine.history()[0]
        self.assertEqual(failed.status,WorkflowStatus.FAILED)
        self.assertEqual(len(failed.test_fix_iterations),3)
        self.assertTrue(failed.manual_intervention_required)
    def test_unrelated_confirmation_is_not_cleared_on_failure(self):
        manager=ConfirmationManager(); manager.request("other","other","Other action")
        engine=WorkflowEngine(self.root,default_registry(),confirmation_manager=manager,patch_tools=self.patch,test_tools=self.tests,review_tools=PassReviewTools())
        with self.assertRaises(Exception): engine.start("feature","Implement export",patch_id="patch-1")
        self.assertTrue(manager.has_pending); self.assertEqual(manager.pending.action_id,"other")

    def test_missing_verifier_cannot_complete(self):
        class MissingVerifier:
            def run_once(self,run): raise WorkflowError("Test Tools are unavailable")
        engine=WorkflowEngine(self.root,default_registry(),confirmation_manager=ConfirmationManager(),patch_tools=self.patch,test_tools=MissingVerifier(),review_tools=PassReviewTools())
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
