"""Extract structured content from raw HTML or Firecrawl markdown."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


_CTA_KEYWORDS = (
    "get", "start", "buy", "sign", "subscribe", "contact",
    "schedule", "book", "call", "free", "try", "request", "quote",
)
_PHONE_RE = re.compile(r"(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def extract_content(content: str, source_url: str) -> dict:
    """Parse scraped content (markdown or HTML) into a structured dict.

    Auto-detects the input format. Firecrawl markdown is passed through
    with light structural parsing; BeautifulSoup HTML is parsed fully.

    Args:
        content: Either markdown (from Firecrawl) or raw HTML (fallback).
        source_url: The URL the content was fetched from.

    Returns:
        Dict with the same shape regardless of input format:
        title, meta_description, headings, body_text, links, forms,
        cta_buttons, contact_info, image_count, nav_structure.
    """
    if _looks_like_markdown(content):
        return _extract_from_markdown(content, source_url)
    return _extract_from_html(content, source_url)


def _looks_like_markdown(content: str) -> bool:
    """Heuristic: does this look like markdown rather than HTML?"""
    if not content:
        return False
    stripped = content.lstrip()
    # HTML detection wins if we see real tags
    lower = stripped[:2000].lower()
    if "<html" in lower or "<!doctype" in lower or "<body" in lower:
        return False
    # Markdown signals: starts with #, has # heading lines, or [text](url) links
    if stripped.startswith("#"):
        return True
    if re.search(r"^#{1,6}\s+\S", content, re.MULTILINE):
        return True
    if re.search(r"\[[^\]]+\]\([^)]+\)", content):
        # Tag-free content with markdown links
        if lower.count("<") < 3:
            return True
    return False


def _extract_from_markdown(md: str, source_url: str) -> dict:
    """Parse markdown content into the structured content dict."""
    headings = {"h1": [], "h2": [], "h3": []}
    for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", md, re.MULTILINE):
        level = len(match.group(1))
        text = match.group(2).strip().rstrip("#").strip()
        if 1 <= level <= 3:
            headings[f"h{level}"].append(text)

    title = headings["h1"][0] if headings["h1"] else ""

    links = []
    for m in re.finditer(r"(?<!\!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", md):
        text = m.group(1).strip()
        href = m.group(2).strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            resolved = href
        else:
            resolved = urljoin(source_url, href)
        links.append({"text": text, "href": resolved})

    cta_buttons = []
    for link in links:
        text_lower = link["text"].lower()
        if any(kw in text_lower for kw in _CTA_KEYWORDS):
            cta_buttons.append(link["text"])

    phones = list(dict.fromkeys(_PHONE_RE.findall(md)))
    emails = list(dict.fromkeys(_EMAIL_RE.findall(md)))
    tel_links = [l["href"] for l in links if l["href"].startswith("tel:")]

    image_count = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", md))

    return {
        "title": title,
        "meta_description": "",
        "headings": headings,
        "body_text": md,
        "links": links,
        "forms": [],
        "cta_buttons": cta_buttons,
        "contact_info": {
            "phones": phones,
            "emails": emails,
            "tel_links": tel_links,
            "has_address": False,
        },
        "image_count": image_count,
        "nav_structure": [],
    }


def _extract_from_html(html: str, source_url: str) -> dict:
    """Parse raw HTML content into the structured content dict."""
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else ""

    meta_tag = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
    meta_description = meta_tag.get("content", "") if meta_tag else ""

    headings = {}
    for level in ("h1", "h2", "h3"):
        headings[level] = [tag.get_text(strip=True) for tag in soup.find_all(level)]

    body = soup.find("body")
    body_text = body.get_text(separator=" ", strip=True) if body else ""

    links = []
    for a in soup.find_all("a", href=True):
        links.append({
            "text": a.get_text(strip=True),
            "href": urljoin(source_url, a["href"]),
        })

    forms = []
    for form in soup.find_all("form"):
        forms.append({
            "action": urljoin(source_url, form.get("action", "")),
            "method": form.get("method", "get").upper(),
            "inputs": [
                inp.get("type", "text") for inp in form.find_all("input")
            ],
        })

    cta_buttons = []
    for btn in soup.find_all(["button", "a"]):
        text = btn.get_text(strip=True).lower()
        if any(kw in text for kw in _CTA_KEYWORDS):
            cta_buttons.append(btn.get_text(strip=True))

    full_text = soup.get_text()
    tel_links = [a["href"] for a in soup.find_all("a", href=re.compile(r"^tel:"))]

    contact_info = {
        "phones": list(dict.fromkeys(_PHONE_RE.findall(full_text))),
        "emails": list(dict.fromkeys(_EMAIL_RE.findall(full_text))),
        "tel_links": tel_links,
        "has_address": bool(soup.find("address")),
    }

    image_count = len(soup.find_all("img"))

    nav = soup.find("nav")
    nav_structure = []
    if nav:
        for a in nav.find_all("a", href=True):
            nav_structure.append({
                "text": a.get_text(strip=True),
                "href": urljoin(source_url, a["href"]),
            })

    return {
        "title": title,
        "meta_description": meta_description,
        "headings": headings,
        "body_text": body_text,
        "links": links,
        "forms": forms,
        "cta_buttons": cta_buttons,
        "contact_info": contact_info,
        "image_count": image_count,
        "nav_structure": nav_structure,
    }
