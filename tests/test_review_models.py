import unittest
from review.models import ReviewFinding,ReviewReport

class ReviewModelTests(unittest.TestCase):
    def finding(self,severity="high",category="correctness"):
        return ReviewFinding("finding-1",severity,category,"core/a.py",2,"problem","fix","evidence")
    def test_round_trip(self):
        report=ReviewReport.create("workflow-"+"a"*32,1,["patch-1"],["core/a.py"],[self.finding()],"reviewed")
        self.assertEqual(ReviewReport.from_dict(report.to_dict()).to_dict(),report.to_dict())
    def test_unknown_severity_rejected(self):
        with self.assertRaises(ValueError): self.finding("urgent")
    def test_unknown_category_rejected(self):
        with self.assertRaises(ValueError): self.finding(category="style")
    def test_model_blocking_field_is_not_trusted(self):
        data=self.finding("critical").to_dict(); data["blocking"]=True
        self.assertFalse(ReviewFinding.from_dict(data).blocking)

if __name__=="__main__": unittest.main()
