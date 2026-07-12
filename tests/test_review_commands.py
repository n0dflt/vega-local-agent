import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from core.command_handler import handle_workflow_command

class ReviewCommandTests(unittest.TestCase):
    def test_review_before_result(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(handle_workflow_command("/workflow review",Path(temp)),"No review result is available.")
    def test_help_mentions_review(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIn("/workflow review",handle_workflow_command("/workflow",Path(temp)))
    def test_review_shows_latest_report(self):
        report={"review_id":"review-1","workflow_id":"workflow-"+"a"*32,"patch_iteration":1,"reviewed_patch_ids":["patch-1"],"reviewed_files":["a.py"],"findings":[],"blocking_findings":[],"highest_severity":"info","passed":True,"summary":"clean","reviewer_error":"","created_at":"test"}
        engine=SimpleNamespace(status=lambda:SimpleNamespace(review_results=[report]))
        text=handle_workflow_command("/workflow review",engine=engine)
        self.assertIn("Review status: passed",text)

if __name__=="__main__": unittest.main()
