"""Strict serializable models for controlled reviews."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class Severity(str, Enum):
    INFO="info"; LOW="low"; MEDIUM="medium"; HIGH="high"; CRITICAL="critical"


class FindingCategory(str, Enum):
    CORRECTNESS="correctness"; SECURITY="security"; REGRESSION="regression"
    TEST_COVERAGE="test_coverage"; ARCHITECTURE="architecture"
    MAINTAINABILITY="maintainability"; PERFORMANCE="performance"
    DOCUMENTATION="documentation"


def _text(value: Any, name: str, *, empty: bool=False) -> str:
    if not isinstance(value,str) or (not empty and not value.strip()):
        raise ValueError(f"{name} must be a non-empty string.")
    return value.strip()


@dataclass(slots=True)
class ReviewFinding:
    finding_id: str
    severity: str
    category: str
    file: str
    line: int | None
    message: str
    recommendation: str
    evidence: str
    blocking: bool=False

    def __post_init__(self):
        self.finding_id=_text(self.finding_id,"finding_id")
        if not self.finding_id.startswith("finding-"): raise ValueError("Invalid finding_id.")
        self.severity=Severity(self.severity).value
        self.category=FindingCategory(self.category).value
        self.file=_text(self.file,"file")
        if self.line is not None and (isinstance(self.line,bool) or not isinstance(self.line,int) or self.line < 1):
            raise ValueError("line must be a positive integer or null.")
        self.message=_text(self.message,"message")
        self.recommendation=_text(self.recommendation,"recommendation")
        self.evidence=_text(self.evidence,"evidence")
        if not isinstance(self.blocking,bool): raise ValueError("blocking must be boolean.")

    def to_dict(self): return asdict(self)
    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict): raise ValueError("Finding must be an object.")
        values=dict(data)
        values["blocking"]=False
        return cls(**values)


@dataclass(slots=True)
class ReviewRequest:
    workflow_id: str
    workflow_type: str
    task: str
    plan: list[str]
    patch_iteration: int
    patch_id: str
    applied_patches: list[dict[str,Any]]
    changed_files: list[str]
    verification_results: list[dict[str,Any]]
    project_context: dict[str,Any]
    relevant_tests: list[str]

    def __post_init__(self):
        for name in ("workflow_id","workflow_type","task","patch_id"):
            setattr(self,name,_text(getattr(self,name),name))
        if isinstance(self.patch_iteration,bool) or not isinstance(self.patch_iteration,int) or self.patch_iteration < 1:
            raise ValueError("patch_iteration must be positive.")
        for name in ("plan","applied_patches","changed_files","verification_results","relevant_tests"):
            if not isinstance(getattr(self,name),list): raise ValueError(f"{name} must be a list.")
        if not isinstance(self.project_context,dict): raise ValueError("project_context must be an object.")

    def to_dict(self): return asdict(self)


@dataclass(slots=True)
class ReviewReport:
    review_id: str
    workflow_id: str
    patch_iteration: int
    reviewed_patch_ids: list[str]
    reviewed_files: list[str]
    findings: list[ReviewFinding]=field(default_factory=list)
    blocking_findings: list[ReviewFinding]=field(default_factory=list)
    highest_severity: str="info"
    passed: bool=False
    summary: str=""
    reviewer_error: str=""
    created_at: str=field(default_factory=lambda:datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        self.review_id=_text(self.review_id,"review_id")
        self.workflow_id=_text(self.workflow_id,"workflow_id")
        if isinstance(self.patch_iteration,bool) or not isinstance(self.patch_iteration,int) or self.patch_iteration < 1: raise ValueError("Invalid patch_iteration.")
        self.highest_severity=Severity(self.highest_severity).value
        self.findings=[x if isinstance(x,ReviewFinding) else ReviewFinding.from_dict(x) for x in self.findings]
        self.blocking_findings=[x if isinstance(x,ReviewFinding) else ReviewFinding.from_dict(x) for x in self.blocking_findings]
        if not all(isinstance(x,str) and x.strip() for x in self.reviewed_patch_ids+self.reviewed_files): raise ValueError("Invalid reviewed paths or patch IDs.")
        if not isinstance(self.passed,bool): raise ValueError("passed must be boolean.")
        self.summary=_text(self.summary,"summary")
        if not isinstance(self.reviewer_error,str): raise ValueError("reviewer_error must be a string.")
        if self.passed and self.blocking_findings: raise ValueError("A passed review cannot contain blocking findings.")

    def to_dict(self): return asdict(self)
    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict): raise ValueError("Review report must be an object.")
        return cls(**data)

    @classmethod
    def create(cls,workflow_id,patch_iteration,patch_ids,files,findings,summary):
        return cls(f"review-{uuid4().hex}",workflow_id,patch_iteration,patch_ids,files,findings,[],"info",False,summary)
