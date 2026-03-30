"""Parse Claude's audit analysis and render the HTML report."""

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def _parse_findings(section_text: str) -> list[dict]:
    """Parse a section's finding blocks separated by '---'.

    Returns:
        List of dicts with keys: finding, severity, impact, fix, monthly_loss.
    """
    blocks = re.split(r"\n---\s*\n", section_text.strip())
    findings = []
    for block in blocks:
        finding = {}
        for key in ("FINDING", "SEVERITY", "IMPACT", "FIX"):
            match = re.search(rf"{key}:\s*(.+)", block)
            finding[key.lower()] = match.group(1).strip() if match else ""
        # Parse monthly loss estimate
        loss_match = re.search(r"MONTHLY_LOSS_ESTIMATE:\s*\$?([\d,]+)", block)
        finding["monthly_loss"] = (
            int(loss_match.group(1).replace(",", "")) if loss_match else 0
        )
        if finding["finding"]:
            findings.append(finding)
    return findings


def _parse_analysis(analysis: str) -> dict:
    """Parse the full Claude analysis string into structured sections.

    Returns:
        Dict with keys: executive_summary, lead_leaks, conversion_leaks,
        follow_up_leaks, priority_fixes, leak_count, total_monthly_loss.
    """
    result = {}

    # Executive summary
    match = re.search(
        r"EXECUTIVE_SUMMARY:\s*\n(.+?)(?=\nLEAD_LEAKS:)", analysis, re.DOTALL
    )
    result["executive_summary"] = match.group(1).strip() if match else ""

    # Lead leaks
    match = re.search(
        r"LEAD_LEAKS:\s*\n(.+?)(?=\nCONVERSION_LEAKS:)", analysis, re.DOTALL
    )
    result["lead_leaks"] = _parse_findings(match.group(1)) if match else []

    # Conversion leaks
    match = re.search(
        r"CONVERSION_LEAKS:\s*\n(.+?)(?=\nFOLLOW_UP_LEAKS:)", analysis, re.DOTALL
    )
    result["conversion_leaks"] = _parse_findings(match.group(1)) if match else []

    # Follow-up leaks
    match = re.search(
        r"FOLLOW_UP_LEAKS:\s*\n(.+?)(?=\nPRIORITY_FIXES:)", analysis, re.DOTALL
    )
    result["follow_up_leaks"] = _parse_findings(match.group(1)) if match else []

    # Priority fixes
    fixes = re.findall(r"\d+\.\s*(.+)", analysis.split("PRIORITY_FIXES:")[-1])
    result["priority_fixes"] = [f.strip() for f in fixes[:3]]

    # Leak count
    result["leak_count"] = {}
    for label, key in [
        ("Lead Leaks", "lead"),
        ("Conversion Leaks", "conversion"),
        ("Follow-Up Leaks", "follow_up"),
        ("Total", "total"),
    ]:
        match = re.search(rf"{label}:\s*(\d+)", analysis)
        result["leak_count"][key] = int(match.group(1)) if match else 0

    # Total monthly loss
    loss_match = re.search(r"TOTAL_MONTHLY_LOSS:\s*\$?([\d,]+)", analysis)
    result["total_monthly_loss"] = (
        int(loss_match.group(1).replace(",", "")) if loss_match else 0
    )

    return result


def generate_report(
    analysis: str, business_name: str, url: str, timestamp: str,
    industry=None,
) -> str:
    """Parse Claude's analysis and render the HTML report.

    Args:
        analysis: Raw analysis string from call_claude.
        business_name: Name of the business being audited.
        url: URL that was audited.
        timestamp: Human-readable timestamp string.
        industry: Optional dict of industry-specific data from detect_industry.

    Returns:
        Rendered HTML string.
    """
    parsed = _parse_analysis(analysis)

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("report.html")

    return template.render(
        business_name=business_name,
        url=url,
        timestamp=timestamp,
        industry=industry or {},
        **parsed,
    )
