"""Extract brand elements (favicon, primary color, name) from a business homepage.

Brand extraction is best-effort and MUST never block the audit pipeline.
The public `extract_brand()` runs the work in a thread with a 3-second cap
and returns an empty-ish dict on any timeout or failure.
"""

import concurrent.futures
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

_EMPTY = {
    "logo_url": None,
    "primary_color": None,
    "business_name": None,
    "all_logos": [],
}

_BRAND_TIMEOUT_SECONDS = 3


def extract_brand(url: str) -> dict:
    """Fetch a homepage and extract brand signals with a hard 3s timeout.

    Args:
        url: The business homepage URL.

    Returns:
        Dict with keys: logo_url, primary_color, business_name, all_logos.
        On timeout or any failure, returns an empty-valued dict — never raises.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_extract_brand_sync, url)
        try:
            return future.result(timeout=_BRAND_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            print(f"[extract_brand] Timeout after {_BRAND_TIMEOUT_SECONDS}s for {url}")
            return dict(_EMPTY)
        except Exception as e:
            print(f"[extract_brand] Error for {url}: {type(e).__name__}: {e}")
            return dict(_EMPTY)


def _extract_brand_sync(url: str) -> dict:
    """Inner synchronous implementation. Never called directly from app code."""
    result = dict(_EMPTY)

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=3, allow_redirects=True)
        resp.raise_for_status()
    except Exception:
        return result

    try:
        return _parse_brand(resp.text, url, result)
    except Exception:
        return result


def _parse_brand(html: str, url: str, result: dict) -> dict:
    """Parse brand elements from HTML. Separated so caller can catch errors."""
    soup = BeautifulSoup(html, "html.parser")

    # ── Logo extraction ──────────────────────────────────────────────
    logo_candidates = []

    # og:image
    og_image = soup.find("meta", attrs={"property": "og:image"})
    if og_image and og_image.get("content"):
        logo_candidates.append(urljoin(url, og_image["content"]))

    # apple-touch-icon
    apple_icon = soup.find("link", rel=lambda v: v and "apple-touch-icon" in " ".join(v).lower())
    if apple_icon and apple_icon.get("href"):
        logo_candidates.append(urljoin(url, apple_icon["href"]))

    # link[rel*=icon] (favicon variants)
    for icon_link in soup.find_all("link", rel=lambda v: v and "icon" in " ".join(v).lower()):
        href = icon_link.get("href")
        if href:
            logo_candidates.append(urljoin(url, href))

    # img tags with "logo" in src or alt
    for img in soup.find_all("img"):
        src = img.get("src", "")
        alt = img.get("alt", "")
        if "logo" in src.lower() or "logo" in alt.lower():
            if src:
                logo_candidates.append(urljoin(url, src))

    # Deduplicate while preserving order
    seen = set()
    unique_logos = []
    for logo in logo_candidates:
        if logo not in seen:
            seen.add(logo)
            unique_logos.append(logo)
    result["all_logos"] = unique_logos

    # Pick the best logo: prefer square-ish, prefer PNG/SVG over ICO
    def _logo_score(logo_url: str) -> int:
        """Higher score = better candidate."""
        score = 0
        lower = logo_url.lower()
        if lower.endswith(".svg"):
            score += 10
        elif lower.endswith(".png"):
            score += 8
        elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
            score += 5
        elif lower.endswith(".ico"):
            score += 1
        # Prefer URLs with "logo" in path
        if "logo" in lower:
            score += 6
        # Prefer apple-touch-icon (usually 180x180 square)
        if "apple-touch-icon" in lower:
            score += 4
        # Deprioritize og:image (often wide banners)
        if logo_url == (og_image and og_image.get("content") and urljoin(url, og_image["content"])):
            score -= 3
        return score

    if unique_logos:
        result["logo_url"] = max(unique_logos, key=_logo_score)

    # ── Primary color extraction ─────────────────────────────────────
    primary_color = None

    # 1. meta[name=theme-color]
    theme_meta = soup.find("meta", attrs={"name": "theme-color"})
    if theme_meta and theme_meta.get("content"):
        color = theme_meta["content"].strip()
        if color.startswith("#") or color.startswith("rgb"):
            primary_color = color

    # 2. Most dominant color from inline CSS
    if not primary_color:
        color_counts = {}
        color_pattern = re.compile(
            r"(?:background-color|background|color)\s*:\s*(#[0-9a-fA-F]{3,8}|rgb[a]?\([^)]+\))"
        )

        # From <style> tags
        for style_tag in soup.find_all("style"):
            if style_tag.string:
                for match in color_pattern.findall(style_tag.string):
                    normalized = match.strip().lower()
                    # Skip black/white/transparent
                    if normalized in ("#000", "#000000", "#fff", "#ffffff", "rgb(0,0,0)", "rgb(255,255,255)"):
                        continue
                    color_counts[normalized] = color_counts.get(normalized, 0) + 1

        # From style attributes
        for tag in soup.find_all(attrs={"style": True}):
            style_val = tag["style"]
            for match in color_pattern.findall(style_val):
                normalized = match.strip().lower()
                if normalized in ("#000", "#000000", "#fff", "#ffffff", "rgb(0,0,0)", "rgb(255,255,255)"):
                    continue
                color_counts[normalized] = color_counts.get(normalized, 0) + 1

        if color_counts:
            primary_color = max(color_counts, key=color_counts.get)

    result["primary_color"] = primary_color

    # ── Business name extraction ─────────────────────────────────────
    business_name = None
    strip_suffixes = re.compile(
        r"\s*[|–—-]\s*(home|homepage|official site|official website|welcome|"
        r"main|index|default|landing).*$",
        re.IGNORECASE,
    )

    # Priority order: og:site_name, og:title, application-name, h1, title
    og_site_name = soup.find("meta", attrs={"property": "og:site_name"})
    if og_site_name and og_site_name.get("content"):
        business_name = og_site_name["content"].strip()

    if not business_name:
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content"):
            business_name = strip_suffixes.sub("", og_title["content"].strip())

    if not business_name:
        app_name = soup.find("meta", attrs={"name": "application-name"})
        if app_name and app_name.get("content"):
            business_name = app_name["content"].strip()

    if not business_name:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            business_name = strip_suffixes.sub("", h1.get_text(strip=True))

    if not business_name:
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            business_name = strip_suffixes.sub("", title_tag.string.strip())

    result["business_name"] = business_name

    return result

