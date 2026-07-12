import tempfile,unittest
from pathlib import Path
from review.models import ReviewFinding,ReviewReport
from workflows import WorkflowEngine,default_registry
from workflows.models import WorkflowError,WorkflowStatus

class Patch:
    def __init__(self): self.states={}
    def prepare(self,run):
        pid=run.artifacts["requested_patch_id"]; self.states[pid]="pending"
        return {"patch_id":pid,"status":"pending","target_path":pid+".py"}
    def apply(self,pid,confirmed=False):
        self.states[pid]="applied"; return {"ok":True,"data":{"patch_id":pid,"status":"applied","target_path":pid+".py"}}
    def inspect(self,pid): return {"patch_id":pid,"status":self.states[pid],"target_path":pid+".py"}
class Tests:
    def __init__(self,results): self.results=list(results); self.runs=0
    def run_once(self,run):
        value=self.results[self.runs]; self.runs+=1; return {"ok":value,"error":None if value else "failed"}
class Reviews:
    def __init__(self,severities): self.severities=list(severities); self.runs=0
    def run_once(self,run):
        severity=self.severities[self.runs]; self.runs+=1
        findings=[] if severity is None else [ReviewFinding(f"finding-{self.runs}",severity,"correctness",run.changed_files[-1],1,"p","r","e",severity in {"high","critical"})]
        report=ReviewReport.create(run.workflow_id,len(run.test_fix_iterations),[(run.patch or {})["patch_id"]],list(run.changed_files),findings,"done")
        report.blocking_findings=[f for f in findings if f.blocking]; report.highest_severity=severity or "info"; report.passed=not report.blocking_findings
        return report.to_dict()
class BrokenReviews:
    def run_once(self,run): raise RuntimeError("review provider offline")
class ErrorPassedReviews:
    def run_once(self,run):
        report=ReviewReport.create(run.workflow_id,len(run.test_fix_iterations),[(run.patch or {})["patch_id"]],list(run.changed_files),[],"invalid")
        report.passed=True; report.reviewer_error="timeout"
        return report.to_dict()
class WorkflowReviewTests(unittest.TestCase):
    def engine(self,tests,reviews):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        return WorkflowEngine(Path(self.temp.name),default_registry(),patch_tools=Patch(),test_tools=tests,review_tools=reviews)
    def test_failed_verification_skips_review(self):
        reviews=Reviews([None]); engine=self.engine(Tests([False]),reviews); engine.start("bugfix","fix",patch_id="p1")
        self.assertEqual(engine.confirm().status,WorkflowStatus.WAITING_PATCH); self.assertEqual(reviews.runs,0)
    def test_passed_verification_reviews_once_and_completes(self):
        reviews=Reviews([None]); engine=self.engine(Tests([True]),reviews); engine.start("bugfix","fix",patch_id="p1")
        self.assertEqual(engine.confirm().status,WorkflowStatus.COMPLETED); self.assertEqual(reviews.runs,1)
    def test_non_blocking_findings_are_preserved_and_complete(self):
        reviews=Reviews(["medium"]); engine=self.engine(Tests([True]),reviews); engine.start("bugfix","fix",patch_id="p1")
        completed=engine.confirm(); self.assertEqual(completed.status,WorkflowStatus.COMPLETED)
        self.assertEqual(completed.review_results[-1]["highest_severity"],"medium")
    def test_blocking_review_waits_for_confirmed_patch_then_reviews_again(self):
        reviews=Reviews(["high",None]); engine=self.engine(Tests([True,True]),reviews); engine.start("bugfix","fix",patch_id="p1")
        waiting=engine.confirm(); self.assertEqual(waiting.patch_request_reason,"review_findings")
        engine.attach_patch("p2"); completed=engine.confirm()
        self.assertEqual(completed.status,WorkflowStatus.COMPLETED); self.assertEqual(reviews.runs,2)
    def test_resume_does_not_repeat_saved_review(self):
        reviews=Reviews(["high"]); engine=self.engine(Tests([True]),reviews); engine.start("bugfix","fix",patch_id="p1"); engine.confirm()
        self.assertEqual(engine.resume().status,WorkflowStatus.WAITING_PATCH); self.assertEqual(reviews.runs,1)
    def test_blocking_review_at_limit_fails_closed(self):
        reviews=Reviews(["high","high","critical"]); engine=self.engine(Tests([True,True,True]),reviews)
        engine.start("bugfix","fix",patch_id="p1"); engine.confirm()
        engine.attach_patch("p2"); engine.confirm(); engine.attach_patch("p3")
        with self.assertRaises(WorkflowError): engine.confirm()
        failed=engine.history()[0]; self.assertEqual(failed.status,WorkflowStatus.FAILED)
        self.assertTrue(failed.manual_intervention_required)
    def test_review_provider_error_fails_closed(self):
        engine=self.engine(Tests([True]),BrokenReviews()); engine.start("bugfix","fix",patch_id="p1")
        with self.assertRaises(RuntimeError): engine.confirm()
        self.assertTrue(engine.history()[0].manual_intervention_required)
    def test_reviewer_error_cannot_complete_even_when_passed(self):
        engine=self.engine(Tests([True]),ErrorPassedReviews()); engine.start("bugfix","fix",patch_id="p1")
        with self.assertRaises(WorkflowError): engine.confirm()
        failed=engine.history()[0]
        self.assertEqual(failed.status,WorkflowStatus.FAILED)
        self.assertTrue(failed.manual_intervention_required)

if __name__=="__main__": unittest.main()
