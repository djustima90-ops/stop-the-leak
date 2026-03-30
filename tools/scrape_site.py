"""Fetch raw HTML from a given URL."""

import requests


def scrape_site(url: str) -> str:
    """Fetch and return the raw HTML of a single page.

    Args:
        url: Full URL to fetch (including scheme).

    Returns:
        Raw HTML string.

    Raises:
        requests.RequestException: On any HTTP or connection error.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
    response.raise_for_status()
    return response.text
