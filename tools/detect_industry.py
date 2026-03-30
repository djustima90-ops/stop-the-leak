"""Detect business industry from extracted site content and load industry data."""

import json
from pathlib import Path

INDUSTRIES_PATH = Path(__file__).resolve().parent.parent / "data" / "industries.json"


def _load_industries() -> dict:
    """Load the industries data from JSON."""
    return json.loads(INDUSTRIES_PATH.read_text())


def detect_industry(structured_content: dict) -> dict:
    """Match site content against industry keyword lists and return the best match.

    Args:
        structured_content: Dict of extracted page content from extract_content.

    Returns:
        Dict with the matched industry data, including a 'key' field for the match ID.
    """
    industries = _load_industries()
    searchable = " ".join([
        structured_content.get("title", ""),
        structured_content.get("meta_description", ""),
        " ".join(structured_content.get("headings", {}).get("h1", [])),
        " ".join(structured_content.get("headings", {}).get("h2", [])),
        structured_content.get("body_text", "")[:2000],
    ]).lower()

    best_key = "default"
    best_score = 0

    for key, data in industries.items():
        if key == "default":
            continue
        score = sum(1 for kw in data["keywords"] if kw in searchable)
        if score > best_score:
            best_score = score
            best_key = key

    result = industries[best_key].copy()
    result["key"] = best_key
    return result
