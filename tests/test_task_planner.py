import unittest

from planner import TaskPlanner


class TaskPlannerTests(unittest.TestCase):
    def test_builds_deterministic_plan(self):
        steps = ["Analyze", "Plan"]
        plan = TaskPlanner().create_plan("Task", {"related_files": ["core/app.py"]}, steps, "feature")
        self.assertIn("Task", plan[0])
        self.assertIn("core/app.py", plan[1])
        self.assertIn("Analyze", plan[2])

    def test_rejects_empty_task(self):
        with self.assertRaises(ValueError):
            TaskPlanner().create_plan(" ", {}, ["Analyze"])


if __name__ == "__main__":
    unittest.main()
