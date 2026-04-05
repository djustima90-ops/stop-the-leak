"""Send structured site content to Claude for leak audit analysis.

Uses Anthropic tool_use to force Claude to return a strict JSON schema.
Callers receive a dict — no prose parsing.
"""

import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

PROMPT_PATH = Path(__file__).resolve().parent.parent / "workflows" / "leak_audit.md"

AUDIT_TOOL = {
    "name": "generate_audit",
    "description": (
        "Return a structured revenue leak audit for the provided website. "
        "Every finding must include a dollar estimate and a concrete fix."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "executive_summary": {
                "type": "string",
                "description": (
                    "2-4 sentence summary naming the business, their vertical, "
                    "and the total estimated monthly loss."
                ),
            },
            "grade": {
                "type": "string",
                "enum": ["A", "B", "C", "D", "F"],
                "description": "Letter grade for the site's revenue health.",
            },
            "findings": {
                "type": "array",
                "description": "List of leak findings.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": [
                                "Lead Leak",
                                "Conversion Leak",
                                "Follow-Up Leak",
                            ],
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["HIGH", "MEDIUM", "LOW"],
                        },
                        "monthly_loss": {"type": "number"},
                        "impact": {"type": "string"},
                        "fix": {"type": "string"},
                    },
                    "required": [
                        "title",
                        "category",
                        "severity",
                        "monthly_loss",
                        "impact",
                        "fix",
                    ],
                },
            },
        },
        "required": ["executive_summary", "grade", "findings"],
    },
}


def call_claude(structured_content: dict, industry=None) -> dict:
    """Send site content to Claude and return the audit as structured JSON.

    Args:
        structured_content: Dict of extracted page content from extract_content.
        industry: Optional dict of industry-specific data from detect_industry.

    Returns:
        Dict matching the generate_audit tool schema:
            {executive_summary, grade, findings: [...]}

    Raises:
        anthropic.APITimeoutError, anthropic.RateLimitError, anthropic.APIError
        on API failures. Callers are responsible for handling these.
        ValueError if Claude fails to return a tool_use block.
    """
    prompt_template = PROMPT_PATH.read_text()
    prompt = prompt_template.replace(
        "{site_content}", json.dumps(structured_content, indent=2)
    )

    if industry:
        industry_block = _build_industry_context(industry)
        prompt = prompt.replace("{industry_context}", industry_block)
    else:
        prompt = prompt.replace(
            "{industry_context}",
            "No industry-specific data available. Use general small business assumptions.",
        )

    prompt += (
        "\n\nReturn your audit by calling the generate_audit tool. "
        "Do not return prose. Every finding must include a realistic "
        "monthly_loss dollar estimate."
    )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=5000,
        tools=[AUDIT_TOOL],
        tool_choice={"type": "tool", "name": "generate_audit"},
        messages=[{"role": "user", "content": prompt}],
    )

    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "generate_audit":
            return block.input

    raise ValueError("Claude did not return a generate_audit tool_use block.")


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
