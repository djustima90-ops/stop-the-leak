"""Render the HTML report from Claude's structured audit output."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


_CATEGORY_KEYS = {
    "Lead Leak": "lead_leaks",
    "Conversion Leak": "conversion_leaks",
    "Follow-Up Leak": "follow_up_leaks",
}


def _bucket_findings(findings: list[dict]) -> dict:
    """Split the flat findings list into the three category buckets the
    template expects, and remap `title` → `finding` for template compatibility.
    """
    buckets = {"lead_leaks": [], "conversion_leaks": [], "follow_up_leaks": []}
    for f in findings or []:
        bucket = _CATEGORY_KEYS.get(f.get("category"))
        if not bucket:
            continue
        buckets[bucket].append({
            "finding": f.get("title", ""),
            "severity": f.get("severity", ""),
            "impact": f.get("impact", ""),
            "fix": f.get("fix", ""),
            "monthly_loss": int(f.get("monthly_loss") or 0),
            "category": f.get("category", ""),
        })
    return buckets


def _fallback_report(business_name: str, url: str, timestamp: str, error_detail: str = "") -> str:
    """Return a minimal valid HTML report when rendering fails."""
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
<div class="card"><h2 style="color:#f59e0b;">Report Rendering Failed</h2>
<p>The AI audit completed, but the report could not be rendered. Please try again.</p>
{f'<p style="color:#64748b;font-size:0.85rem;margin-top:1rem;">Debug: {error_detail}</p>' if error_detail else ''}
</div></body></html>"""


def generate_report(
    analysis: dict, business_name: str, url: str, timestamp: str,
    industry=None, brand=None,
) -> str:
    """Render the HTML report from a structured audit dict.

    Args:
        analysis: Structured audit dict from call_claude (tool_use output):
            {executive_summary, grade, findings: [{title, category, severity,
             monthly_loss, impact, fix}, ...]}
        business_name: Name of the business being audited.
        url: URL that was audited.
        timestamp: Human-readable timestamp string.
        industry: Optional dict of industry-specific data.
        brand: Optional dict with logo_url, primary_color, business_name.

    Returns:
        Rendered HTML string.
    """
    try:
        if not analysis or not isinstance(analysis, dict):
            return _fallback_report(business_name, url, timestamp, "Empty analysis")

        findings = analysis.get("findings", []) or []
        buckets = _bucket_findings(findings)

        total_monthly_loss = sum(f["monthly_loss"] for f in findings if f.get("monthly_loss"))
        total_monthly_loss = int(total_monthly_loss)

        leak_count = {
            "lead": len(buckets["lead_leaks"]),
            "conversion": len(buckets["conversion_leaks"]),
            "follow_up": len(buckets["follow_up_leaks"]),
            "total": len(findings),
        }

        # Priority fixes: top 3 findings by monthly_loss
        top_three = sorted(
            findings, key=lambda f: f.get("monthly_loss") or 0, reverse=True
        )[:3]
        priority_fixes = [f.get("fix", "") for f in top_three if f.get("fix")]

        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
        template = env.get_template("report.html")

        return template.render(
            business_name=business_name or "Unknown Business",
            url=url or "",
            timestamp=timestamp or "",
            industry=industry or {},
            brand=brand or {},
            executive_summary=analysis.get("executive_summary", ""),
            grade=analysis.get("grade", ""),
            lead_leaks=buckets["lead_leaks"],
            conversion_leaks=buckets["conversion_leaks"],
            follow_up_leaks=buckets["follow_up_leaks"],
            priority_fixes=priority_fixes,
            leak_count=leak_count,
            total_monthly_loss=total_monthly_loss,
        )
    except Exception as e:
        print(f"[generate_report] FATAL ERROR: {type(e).__name__}: {e}")
        return _fallback_report(
            business_name or "Unknown Business",
            url or "",
            timestamp or "",
            f"{type(e).__name__}: {e}",
        )
