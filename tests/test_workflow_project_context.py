import tempfile,unittest
from pathlib import Path
from workflows.project_context import ProjectContextAdapter,TaskSystemAdapter

class ProjectContextTests(unittest.TestCase):
    def test_collects_real_workspace_and_active_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); (root/"core").mkdir(); (root/"tests").mkdir(); (root/"docs").mkdir()
            (root/"core/parser.py").write_text("",encoding="utf-8"); (root/"tests/test_parser.py").write_text("",encoding="utf-8"); (root/"docs/parser.md").write_text("",encoding="utf-8")
            task=TaskSystemAdapter(root).manager.create_task("Fix parser")
            context=ProjectContextAdapter(root).collect("Fix parser error","bugfix")
            self.assertIn("core/parser.py",context["related_files"]); self.assertIn("tests/test_parser.py",context["tests"]); self.assertIn("docs/parser.md",context["documentation"])
            self.assertEqual(context["active_task"]["id"],task["id"]); self.assertTrue(context["workspace_available"])
            saved=TaskSystemAdapter(root).link_plan(task["id"],["Inspect parser","Apply fix"])
            self.assertEqual(saved["plan"],["Inspect parser","Apply fix"])

if __name__=="__main__": unittest.main()
