"""Extract structured content from raw HTML."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def extract_content(html: str, source_url: str) -> dict:
    """Parse raw HTML and return structured page content.

    Args:
        html: Raw HTML string.
        source_url: The URL the HTML was fetched from (used to resolve relative links).

    Returns:
        Dict with keys: title, meta_description, headings, body_text, links,
        forms, cta_buttons, contact_info, image_count, nav_structure.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = soup.title.get_text(strip=True) if soup.title else ""

    # Meta description
    meta_tag = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
    meta_description = meta_tag.get("content", "") if meta_tag else ""

    # Headings
    headings = {}
    for level in ("h1", "h2", "h3"):
        headings[level] = [tag.get_text(strip=True) for tag in soup.find_all(level)]

    # Body text
    body = soup.find("body")
    body_text = body.get_text(separator=" ", strip=True) if body else ""

    # Links
    links = []
    for a in soup.find_all("a", href=True):
        links.append({
            "text": a.get_text(strip=True),
            "href": urljoin(source_url, a["href"]),
        })

    # Forms
    forms = []
    for form in soup.find_all("form"):
        forms.append({
            "action": urljoin(source_url, form.get("action", "")),
            "method": form.get("method", "get").upper(),
            "inputs": [
                inp.get("type", "text") for inp in form.find_all("input")
            ],
        })

    # CTA buttons
    cta_buttons = []
    for btn in soup.find_all(["button", "a"]):
        text = btn.get_text(strip=True).lower()
        cta_keywords = (
            "get", "start", "buy", "sign", "subscribe", "contact",
            "schedule", "book", "call", "free", "try", "request", "quote",
        )
        if any(kw in text for kw in cta_keywords):
            cta_buttons.append(btn.get_text(strip=True))

    # Contact info
    full_text = soup.get_text()
    phone_pattern = re.compile(
        r"(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})"
    )
    email_pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    tel_links = [a["href"] for a in soup.find_all("a", href=re.compile(r"^tel:"))]

    contact_info = {
        "phones": phone_pattern.findall(full_text),
        "emails": email_pattern.findall(full_text),
        "tel_links": tel_links,
        "has_address": bool(soup.find("address")),
    }

    # Image count
    image_count = len(soup.find_all("img"))

    # Nav structure
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
