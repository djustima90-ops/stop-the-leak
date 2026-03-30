"""Save a rendered HTML report to the outputs directory."""

import os
import re
from datetime import datetime
from pathlib import Path

# Use /tmp on Vercel (read-only filesystem), local outputs/ otherwise
if os.environ.get("VERCEL"):
    OUTPUTS_DIR = Path("/tmp/outputs")
else:
    OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"


def save_output(html: str, business_name: str) -> Path:
    """Save rendered HTML report to a file in the outputs directory.

    Args:
        html: Rendered HTML report string.
        business_name: Name of the business (used to build the filename slug).

    Returns:
        Path to the saved file.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", business_name.lower()).strip("_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{slug}_{timestamp}.html"

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUTS_DIR / filename
    filepath.write_text(html, encoding="utf-8")

    return filepath
