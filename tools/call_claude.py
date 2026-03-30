"""Send structured site content to Claude for leak audit analysis."""

import json
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

PROMPT_PATH = Path(__file__).resolve().parent.parent / "workflows" / "leak_audit.md"


def call_claude(structured_content: dict) -> str:
    """Send site content to Claude and return the audit analysis.

    Args:
        structured_content: Dict of extracted page content from extract_content.

    Returns:
        Claude's analysis as a string.
    """
    prompt_template = PROMPT_PATH.read_text()
    prompt = prompt_template.replace(
        "{site_content}", json.dumps(structured_content, indent=2)
    )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=5000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
