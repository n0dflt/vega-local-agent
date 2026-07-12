"""Human-readable controlled review reports."""
def build_review_report(report):
    lines=[f"Review status: {'passed' if report.passed else 'blocking findings'}",f"Highest severity: {report.highest_severity}",f"Reviewed patch iteration: {report.patch_iteration}",f"Reviewed files: {len(report.reviewed_files)}",f"Total findings: {len(report.findings)}",f"Blocking findings: {len(report.blocking_findings)}"]
    for finding in report.findings:
        lines.extend(["",f"[{finding.severity.upper()}][{finding.category}]",f"File: {finding.file}",f"Line: {finding.line or 'n/a'}",f"Problem: {finding.message}",f"Recommendation: {finding.recommendation}"])
    return "\n".join(lines)
