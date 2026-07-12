import tempfile,unittest
from pathlib import Path
from review.models import ReviewFinding,ReviewReport
from review.risk_analyzer import ReviewPolicy,RiskAnalyzer

class RiskAnalyzerTests(unittest.TestCase):
    def report(self,severity):
        finding=ReviewFinding("finding-1",severity,"correctness","a.py",1,"p","r","e")
        return ReviewReport.create("workflow-"+"a"*32,1,["patch-1"],["a.py"],[finding],"done")
    def test_high_is_blocking(self): self.assertFalse(RiskAnalyzer().evaluate(self.report("high")).passed)
    def test_medium_is_non_blocking(self): self.assertTrue(RiskAnalyzer().evaluate(self.report("medium")).passed)
    def test_critical_false_is_recomputed_blocking(self):
        report=self.report("critical"); report.findings[0].blocking=False
        self.assertTrue(RiskAnalyzer().evaluate(report).findings[0].blocking)
    def test_medium_true_is_recomputed_non_blocking(self):
        report=self.report("medium"); report.findings[0].blocking=True
        self.assertFalse(RiskAnalyzer().evaluate(report).findings[0].blocking)
    def test_finding_limit_is_fail_closed(self):
        report=self.report("low"); report.findings*=2
        with self.assertRaises(ValueError): RiskAnalyzer(ReviewPolicy(max_findings=1)).evaluate(report)
    def test_corrupt_policy_uses_safe_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"policy.json"; path.write_text("{",encoding="utf-8")
            self.assertIn("high",ReviewPolicy.load(path).blocking_severities)

if __name__=="__main__": unittest.main()
