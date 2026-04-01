"""Send structured site content to Claude for leak audit analysis."""

import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

PROMPT_PATH = Path(__file__).resolve().parent.parent / "workflows" / "leak_audit.md"


def _fallback_analysis() -> str:
    """Return a valid fallback analysis string when the API fails."""
    return (
        "EXECUTIVE_SUMMARY:\n"
        "The AI analysis service is temporarily unavailable. "
        "Please try running the audit again in a few minutes.\n\n"
        "LEAD_LEAKS:\n"
        "FINDING: Analysis unavailable — please retry\n"
        "SEVERITY: Low\n"
        "IMPACT: Unable to complete audit at this time.\n"
        "FIX: Please retry the audit.\n"
        "MONTHLY_LOSS_ESTIMATE: $0\n"
        "---\n\n"
        "CONVERSION_LEAKS:\n"
        "FINDING: Analysis unavailable — please retry\n"
        "SEVERITY: Low\n"
        "IMPACT: Unable to complete audit at this time.\n"
        "FIX: Please retry the audit.\n"
        "MONTHLY_LOSS_ESTIMATE: $0\n"
        "---\n\n"
        "FOLLOW_UP_LEAKS:\n"
        "FINDING: Analysis unavailable — please retry\n"
        "SEVERITY: Low\n"
        "IMPACT: Unable to complete audit at this time.\n"
        "FIX: Please retry the audit.\n"
        "MONTHLY_LOSS_ESTIMATE: $0\n"
        "---\n\n"
        "PRIORITY_FIXES:\n"
        "1. Retry the audit when the service is available\n\n"
        "LEAK_COUNT:\n"
        "Lead Leaks: 1\nConversion Leaks: 1\n"
        "Follow-Up Leaks: 1\nTotal: 3\n\n"
        "TOTAL_MONTHLY_LOSS: $0"
    )


def call_claude(structured_content: dict, industry=None) -> str:
    """Send site content to Claude and return the audit analysis.

    Args:
        structured_content: Dict of extracted page content from extract_content.
        industry: Optional dict of industry-specific data from detect_industry.

    Returns:
        Claude's analysis as a string.
    """
    prompt_template = PROMPT_PATH.read_text()
    prompt = prompt_template.replace(
        "{site_content}", json.dumps(structured_content, indent=2)
    )

    if industry:
        industry_block = _build_industry_context(industry)
        prompt = prompt.replace("{industry_context}", industry_block)
    else:
        prompt = prompt.replace("{industry_context}", "No industry-specific data available. Use general small business assumptions.")

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=5000,
            messages=[{"role": "user", "content": prompt}],
        )
        if not message.content:
            print("[call_claude] Empty response from API (no content blocks)")
            return _fallback_analysis()
        text = message.content[0].text
        if not text or not text.strip():
            print("[call_claude] Empty text in API response")
            return _fallback_analysis()
        return text
    except Exception as e:
        print(f"[call_claude] Anthropic API error: {type(e).__name__}: {e}")
        return _fallback_analysis()


def _build_industry_context(industry: dict) -> str:
    """Format industry data into a context block for the prompt."""
    lines = [
        f"Detected Industry: {industry['name']}",
        f"Typical Monthly Revenue: ${industry['typical_monthly_revenue']:,}",
        f"Typical Annual Revenue: ${industry['typical_annual_revenue']:,}",
        "",
        "Loss Multipliers (as fraction of monthly revenue):",
        f"  High severity: {industry['high_loss_multiplier']} = ${int(industry['typical_monthly_revenue'] * industry['high_loss_multiplier']):,}/month per finding",
        f"  Medium severity: {industry['medium_loss_multiplier']} = ${int(industry['typical_monthly_revenue'] * industry['medium_loss_multiplier']):,}/month per finding",
        f"  Low severity: {industry['low_loss_multiplier']} = ${int(industry['typical_monthly_revenue'] * industry['low_loss_multiplier']):,}/month per finding",
        "",
        "Common Leak Patterns for This Industry:",
    ]
    for pattern in industry.get("top_leak_patterns", []):
        lines.append(f"  - {pattern}")
    lines.append("")
    lines.append(f"Language Style: {industry.get('language_style', '')}")
    lines.append(f"Local Context: {industry.get('local_context', '')}")
    return "\n".join(lines)
