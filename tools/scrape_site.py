"""Fetch site content via Firecrawl, with a BeautifulSoup-compatible fallback.

Primary path: Firecrawl returns clean markdown.
Fallback path: plain `requests.get()` returns raw HTML.

The scraper MUST NEVER crash the audit pipeline. On any failure it either
falls back to the HTML fetcher or raises a standard requests exception
that `/audit` already knows how to handle.
"""

import concurrent.futures
import os
from typing import Optional

import requests
from firecrawl import Firecrawl

_FIRECRAWL_TIMEOUT_SECONDS = 30
_HTML_TIMEOUT_SECONDS = 10

_firecrawl_client: Optional[Firecrawl] = None


def _get_firecrawl_client() -> Optional[Firecrawl]:
    """Return a memoized Firecrawl client, or None if no API key is set."""
    global _firecrawl_client
    if _firecrawl_client is not None:
        return _firecrawl_client
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        return None
    _firecrawl_client = Firecrawl(api_key=api_key)
    return _firecrawl_client


def scrape_site(url: str) -> str:
    """Fetch a page and return its content (markdown preferred, HTML fallback).

    Args:
        url: Full URL to fetch (including scheme).

    Returns:
        Markdown string if Firecrawl succeeds, otherwise raw HTML. Callers
        in `extract_content` detect the format and parse accordingly.

    Raises:
        requests.RequestException: Only if BOTH Firecrawl and the HTML
            fallback fail. `/audit` already handles this.
    """
    markdown = _try_firecrawl(url)
    if markdown:
        return markdown
    return _fallback_html(url)


def _try_firecrawl(url: str) -> str:
    """Call Firecrawl with a hard 30s cap. Returns "" on any failure."""
    client = _get_firecrawl_client()
    if client is None:
        return ""

    def _run() -> str:
        # timeout is in milliseconds in Firecrawl's API
        doc = client.scrape(
            url,
            formats=["markdown"],
            timeout=_FIRECRAWL_TIMEOUT_SECONDS * 1000,
            only_main_content=True,
        )
        return (doc.markdown or "") if doc else ""

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            return future.result(timeout=_FIRECRAWL_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        print(f"[scrape_site] Firecrawl timeout after {_FIRECRAWL_TIMEOUT_SECONDS}s for {url}")
        return ""
    except Exception as e:
        print(f"[scrape_site] Firecrawl error for {url}: {type(e).__name__}: {e}")
        return ""


def _fallback_html(url: str) -> str:
    """BeautifulSoup-compatible HTML fetcher. Raises on hard failure."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(
        url, headers=headers, timeout=_HTML_TIMEOUT_SECONDS, allow_redirects=True,
    )
    response.raise_for_status()
    return response.text
