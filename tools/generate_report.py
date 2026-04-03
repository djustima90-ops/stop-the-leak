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
    print(f"[generate_report] raw analysis length: {len(analysis)}")

    result = {}

    # Executive summary
    try:
        match = re.search(
            r"EXECUTIVE_SUMMARY:\s*\n(.+?)(?=\nLEAD_LEAKS:)", analysis, re.DOTALL
        )
        result["executive_summary"] = match.group(1).strip() if match else ""
    except Exception as e:
        print(f"[generate_report] Failed to parse executive_summary: {e}")
        result["executive_summary"] = ""

    # Lead leaks
    try:
        match = re.search(
            r"LEAD_LEAKS:\s*\n(.+?)(?=\nCONVERSION_LEAKS:)", analysis, re.DOTALL
        )
        result["lead_leaks"] = _parse_findings(match.group(1)) if match else []
    except Exception as e:
        print(f"[generate_report] Failed to parse lead_leaks: {e}")
        result["lead_leaks"] = []

    # Conversion leaks
    try:
        match = re.search(
            r"CONVERSION_LEAKS:\s*\n(.+?)(?=\nFOLLOW_UP_LEAKS:)", analysis, re.DOTALL
        )
        result["conversion_leaks"] = _parse_findings(match.group(1)) if match else []
    except Exception as e:
        print(f"[generate_report] Failed to parse conversion_leaks: {e}")
        result["conversion_leaks"] = []

    # Follow-up leaks
    try:
        match = re.search(
            r"FOLLOW_UP_LEAKS:\s*\n(.+?)(?=\nPRIORITY_FIXES:)", analysis, re.DOTALL
        )
        result["follow_up_leaks"] = _parse_findings(match.group(1)) if match else []
    except Exception as e:
        print(f"[generate_report] Failed to parse follow_up_leaks: {e}")
        result["follow_up_leaks"] = []

    # Priority fixes
    try:
        fixes = re.findall(r"\d+\.\s*(.+)", analysis.split("PRIORITY_FIXES:")[-1])
        result["priority_fixes"] = [f.strip() for f in fixes[:3]]
    except Exception as e:
        print(f"[generate_report] Failed to parse priority_fixes: {e}")
        result["priority_fixes"] = []

    # Leak count
    try:
        result["leak_count"] = {}
        for label, key in [
            ("Lead Leaks", "lead"),
            ("Conversion Leaks", "conversion"),
            ("Follow-Up Leaks", "follow_up"),
            ("Total", "total"),
        ]:
            match = re.search(rf"{label}:\s*(\d+)", analysis)
            result["leak_count"][key] = int(match.group(1)) if match else 0
    except Exception as e:
        print(f"[generate_report] Failed to parse leak_count: {e}")
        result["leak_count"] = {"lead": 0, "conversion": 0, "follow_up": 0, "total": 0}

    # Total monthly loss
    try:
        loss_match = re.search(r"TOTAL_MONTHLY_LOSS:\s*\$?([\d,]+)", analysis)
        result["total_monthly_loss"] = (
            int(loss_match.group(1).replace(",", "")) if loss_match else 0
        )
    except Exception as e:
        print(f"[generate_report] Failed to parse total_monthly_loss: {e}")
        result["total_monthly_loss"] = 0

    total_findings = (
        len(result.get("lead_leaks", []))
        + len(result.get("conversion_leaks", []))
        + len(result.get("follow_up_leaks", []))
    )
    if total_findings == 0:
        print("[generate_report] WARNING: no findings parsed")

    return result


def _fallback_report(business_name: str, url: str, timestamp: str, error_detail: str = "") -> str:
    """Return a minimal valid HTML report when parsing/rendering fails."""
    safe_name = business_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_url = url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Leak Report — {safe_name}</title>
<style>body{{font-family:-apple-system,sans-serif;background:#09101d;color:#e2e8f0;max-width:700px;margin:0 auto;padding:3rem 2rem;}}
h1{{color:#ef4444;}} .card{{background:#111827;border:1px solid #1e293b;border-radius:12px;padding:2rem;margin:1.5rem 0;}}
a{{color:#60a5fa;}}</style></head><body>
<h1>Leak Report</h1>
<div class="card"><p><strong>Business:</strong> {safe_name}</p><p><strong>URL:</strong> {safe_url}</p>
<p><strong>Generated:</strong> {timestamp}</p></div>
<div class="card"><h2 style="color:#f59e0b;">Analysis Could Not Be Fully Parsed</h2>
<p>The AI audit completed, but the report could not be formatted properly. This usually means the AI returned an unexpected format.</p>
<p>Please try running the audit again. If the problem persists, contact support.</p>
{f'<p style="color:#64748b;font-size:0.85rem;margin-top:1rem;">Debug: {error_detail}</p>' if error_detail else ''}
</div></body></html>"""


def generate_report(
    analysis: str, business_name: str, url: str, timestamp: str,
    industry=None, brand=None,
) -> str:
    """Parse Claude's analysis and render the HTML report.

    Args:
        analysis: Raw analysis string from call_claude.
        business_name: Name of the business being audited.
        url: URL that was audited.
        timestamp: Human-readable timestamp string.
        industry: Optional dict of industry-specific data from detect_industry.
        brand: Optional dict with logo_url, primary_color, business_name.

    Returns:
        Rendered HTML string.
    """
    try:
        print(f"[generate_report] Analysis length: {len(analysis) if analysis else 0}")
        print(f"[generate_report] Analysis first 500 chars: {repr(analysis[:500]) if analysis else 'EMPTY'}")

        if not analysis or not analysis.strip():
            print("[generate_report] Empty analysis received, returning fallback")
            return _fallback_report(business_name, url, timestamp, "Empty analysis from AI")

        print(f"[DEBUG] Raw analysis first 1000 chars: {analysis[:1000]}")

        parsed = _parse_analysis(analysis)

        print(f"[DEBUG] Lead leaks parsed: {len(parsed.get('lead_leaks', []))}")
        print(f"[DEBUG] Conversion leaks parsed: {len(parsed.get('conversion_leaks', []))}")
        print(f"[DEBUG] Follow-up leaks parsed: {len(parsed.get('follow_up_leaks', []))}")
        print(f"[DEBUG] Executive summary length: {len(parsed.get('executive_summary', ''))}")

        # Ensure all expected keys exist with safe defaults
        parsed.setdefault("executive_summary", "")
        parsed.setdefault("lead_leaks", [])
        parsed.setdefault("conversion_leaks", [])
        parsed.setdefault("follow_up_leaks", [])
        parsed.setdefault("priority_fixes", [])
        parsed.setdefault("leak_count", {"lead": 0, "conversion": 0, "follow_up": 0, "total": 0})
        parsed.setdefault("total_monthly_loss", 0)

        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
        template = env.get_template("report.html")

        return template.render(
            business_name=business_name or "Unknown Business",
            url=url or "",
            timestamp=timestamp or "",
            industry=industry or {},
            brand=brand or {},
            **parsed,
        )
    except Exception as e:
        print(f"[generate_report] FATAL ERROR: {type(e).__name__}: {e}")
        print(f"[generate_report] Analysis was: {repr(analysis[:1000]) if analysis else 'None'}")
        return _fallback_report(
            business_name or "Unknown Business",
            url or "",
            timestamp or "",
            f"{type(e).__name__}: {e}",
        )
