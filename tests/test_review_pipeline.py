import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from review.models import ReviewFinding,ReviewReport
from review.review_pipeline import ReviewPipeline

class FakeProvider:
    def __init__(self): self.requests=[]
    def review(self,request):
        self.requests.append(request)
        return ReviewReport.create(request.workflow_id,request.patch_iteration,[request.patch_id],request.changed_files,[],"clean")
class StaticProvider:
    def __init__(self,report): self.report=report
    def review(self,request): return self.report

class ReviewPipelineTests(unittest.TestCase):
    def workflow_run(self):
        return SimpleNamespace(workflow_id="workflow-"+"a"*32,workflow_type="feature",task="task",plan=[],test_fix_iterations=[{"patch_id":"patch-1"}],changed_files=["a.py"],verification_results=[{"ok":True}],context={})
    def report(self): return ReviewReport.create("workflow-"+"a"*32,1,["patch-1"],["a.py"],[],"clean")
    def test_request_uses_workflow_evidence_only(self):
        provider=FakeProvider()
        run=SimpleNamespace(workflow_id="workflow-"+"a"*32,workflow_type="feature",task="task",plan=[],test_fix_iterations=[{"patch_id":"patch-1"}],changed_files=["a.py"],verification_results=[{"ok":True}],context={"tests":["test_a.py"]})
        report=ReviewPipeline(Path(tempfile.gettempdir()),provider).run(run)
        self.assertTrue(report.passed); self.assertEqual(provider.requests[0].changed_files,["a.py"])
        self.assertFalse(hasattr(provider.requests[0],"working_tree_diff"))
    def pipeline(self,report): return ReviewPipeline(Path(tempfile.gettempdir()),StaticProvider(report))
    def test_parent_traversal_finding_is_rejected(self):
        report=self.report(); report.findings=[ReviewFinding("finding-1","high","security","../../secret.txt",1,"p","r","e")]
        with self.assertRaises(ValueError): self.pipeline(report).run(self.workflow_run())
    def test_finding_outside_changed_files_is_rejected(self):
        report=self.report(); report.findings=[ReviewFinding("finding-1","high","security","other.py",1,"p","r","e")]
        with self.assertRaises(ValueError): self.pipeline(report).run(self.workflow_run())
    def test_reviewed_files_outside_changed_files_are_rejected(self):
        report=self.report(); report.reviewed_files=["other.py"]
        with self.assertRaises(ValueError): self.pipeline(report).run(self.workflow_run())
    def test_wrong_workflow_id_is_rejected(self):
        report=self.report(); report.workflow_id="workflow-"+"b"*32
        with self.assertRaises(ValueError): self.pipeline(report).run(self.workflow_run())
    def test_wrong_patch_iteration_is_rejected(self):
        report=self.report(); report.patch_iteration=2
        with self.assertRaises(ValueError): self.pipeline(report).run(self.workflow_run())
    def test_unknown_reviewed_patch_is_rejected(self):
        report=self.report(); report.reviewed_patch_ids=["patch-other"]
        with self.assertRaises(ValueError): self.pipeline(report).run(self.workflow_run())
    def test_absolute_and_unc_paths_are_rejected(self):
        for value in (r"C:\outside\file.py",r"\\server\share\file.py"):
            with self.subTest(value=value):
                report=self.report(); report.reviewed_files=[value]
                with self.assertRaises(ValueError): self.pipeline(report).run(self.workflow_run())

if __name__=="__main__": unittest.main()
