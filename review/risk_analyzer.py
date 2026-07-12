"""Fail-closed review policy loading and risk evaluation."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from review.models import ReviewReport,Severity

DEFAULT_BLOCKING=frozenset({"critical","high"})
DEFAULT_CATEGORIES=frozenset({"correctness","security","regression","test_coverage","architecture","maintainability","performance","documentation"})
RANK={"info":0,"low":1,"medium":2,"high":3,"critical":4}

@dataclass(frozen=True,slots=True)
class ReviewPolicy:
    blocking_severities:frozenset[str]=DEFAULT_BLOCKING
    allowed_categories:frozenset[str]=DEFAULT_CATEGORIES
    max_findings:int=100
    fail_closed_on_invalid_report:bool=True
    require_review_after_each_successful_verification:bool=True

    @classmethod
    def load(cls,path):
        try:
            data=json.loads(Path(path).read_text(encoding="utf-8"))
            blocking=frozenset(data["blocking_severities"])
            allowed=frozenset(data["allowed_categories"])
            maximum=data["max_findings"]
            if not DEFAULT_BLOCKING.issubset(blocking) or not blocking.issubset(set(RANK)) or not allowed.issubset(DEFAULT_CATEGORIES) or not allowed or isinstance(maximum,bool) or not 1<=maximum<=1000: raise ValueError
            return cls(blocking,allowed,maximum,bool(data.get("fail_closed_on_invalid_report",True)),bool(data.get("require_review_after_each_successful_verification",True)))
        except (OSError,KeyError,TypeError,ValueError,json.JSONDecodeError): return cls()

class RiskAnalyzer:
    def __init__(self,policy=None): self.policy=policy or ReviewPolicy()
    def evaluate(self,report):
        if not isinstance(report,ReviewReport): raise ValueError("Invalid review report.")
        if len(report.findings)>self.policy.max_findings: raise ValueError("Review finding limit exceeded.")
        if any(f.category not in self.policy.allowed_categories for f in report.findings): raise ValueError("Review category is blocked by policy.")
        for finding in report.findings: finding.blocking=finding.severity in self.policy.blocking_severities
        report.blocking_findings=[f for f in report.findings if f.blocking]
        report.highest_severity=max((f.severity for f in report.findings),key=lambda s:RANK[s],default=Severity.INFO.value)
        report.passed=not report.blocking_findings and not report.reviewer_error
        return report
