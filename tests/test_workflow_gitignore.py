import unittest
from pathlib import Path

class WorkflowGitignoreTests(unittest.TestCase):
    def test_runtime_json_is_ignored_but_gitkeep_is_preserved(self):
        text=(Path(__file__).resolve().parents[1]/".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/workflows/active/*.json",text)
        self.assertIn("data/workflows/history/*.json",text)
        self.assertIn("!data/workflows/active/.gitkeep",text)
        self.assertIn("!data/workflows/history/.gitkeep",text)

if __name__=="__main__": unittest.main()
