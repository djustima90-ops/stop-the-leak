# Stop the Leak — Business Audit Tool
## CLAUDE.md — Agent Instructions

---

## What This Project Is

A web-based tool that accepts a local business URL, scrapes the public-facing website,
analyzes it for lead leaks and conversion gaps using Claude AI, and outputs a structured
"Leak Report" — a professional diagnostic document identifying exactly where the business
is losing leads and what to fix.

**End user:** Me (the operator), initially. Report is shared with business owner prospects.
**Phase 1 goal:** Enter URL → get professional Leak Report. Nothing else.

---

## Tech Stack

- **Language:** Python 3.11+
- **Web framework:** Flask
- **Scraping:** requests + BeautifulSoup4
- **AI:** Anthropic Python SDK — model: claude-sonnet-4-5
- **Report output:** HTML report rendered in browser
- **Secrets:** python-dotenv (.env file only — never hardcode keys)
- **No database** — flat file outputs only

---

## File Structure
```
stop-the-leak/
├── CLAUDE.md
├── app.py
├── .env
├── requirements.txt
├── workflows/
│   └── leak_audit.md
├── tools/
│   ├── scrape_site.py
│   ├── extract_content.py
│   ├── call_claude.py
│   ├── generate_report.py
│   └── save_output.py
├── outputs/
└── templates/
    ├── index.html
    └── report.html
```

---

## Build Sequence — Follow This Exactly

Build in this order. Do not skip ahead. Verify each step works before moving on.
```
Step 1: Scaffold all folders and empty files
Step 2: Create requirements.txt and .env template
Step 3: Build tools/scrape_site.py — test with 1 real URL
Step 4: Build tools/extract_content.py — test with scraped HTML
Step 5: Create workflows/leak_audit.md with full audit prompt
Step 6: Build tools/call_claude.py — test with sample content
Step 7: Build tools/generate_report.py
Step 8: Build tools/save_output.py
Step 9: Build templates/index.html
Step 10: Build templates/report.html
Step 11: Build app.py tying everything together
Step 12: End-to-end test with 3 real business URLs
```

---

## What Each Tool Does

### tools/scrape_site.py
**Input:** URL string
**Does:** Fetches raw HTML using requests with a realistic user-agent header.
Handles redirects, timeouts (10s), and basic HTTP errors.
**Returns:** Raw HTML string or raises a clear exception.
**Does NOT:** Parse or analyze anything.

### tools/extract_content.py
**Input:** Raw HTML string, source URL
**Does:** Uses BeautifulSoup to extract page title, meta description,
headings (H1/H2/H3), body text, links, forms, CTA buttons,
contact info (phone, email, address), image count, nav structure.
**Returns:** Python dict of structured content.
**Does NOT:** Make any judgments.

### tools/call_claude.py
**Input:** Structured content dict
**Does:** Reads audit prompt from workflows/leak_audit.md,
injects structured site content, calls Claude API with claude-sonnet-4-5.
**Returns:** Claude's analysis as a string.
**Token limit:** max_tokens=4000

### tools/generate_report.py
**Input:** Claude analysis string, business name, URL, timestamp
**Does:** Parses Claude's output and populates report.html template.
**Returns:** Rendered HTML string.

### tools/save_output.py
**Input:** Rendered HTML string, business name
**Does:** Saves HTML to outputs/<slug>_<YYYYMMDD_HHMMSS>.html
**Returns:** File path of saved report.

---

## Audit Logic — Claude Must Evaluate These 3 Categories

### CATEGORY 1: LEAD LEAKS
- Is there a visible contact form?
- Is there a phone number? Is it a clickable tel: link?
- Is there an email address visible?
- Is there a live chat widget?
- Is there a Google Business / Maps integration?

### CATEGORY 2: CONVERSION LEAKS
- Is there one clear CTA above the fold?
- Does the headline communicate what the business does?
- Is there a value proposition visible without scrolling?
- Is there social proof — reviews, testimonials, logos?
- Are there trust signals — certifications, awards, years in business?
- Is the page mobile-responsive?

### CATEGORY 3: FOLLOW-UP LEAKS
- Is there a lead magnet or email capture?
- Is there a newsletter signup?
- Are there blog posts updated in the last 6 months?
- Are social media links present?

### Claude Must Return This Exact Format:
```
EXECUTIVE_SUMMARY:
[2-3 sentence summary]

LEAD_LEAKS:
FINDING: [specific finding]
SEVERITY: [High/Medium/Low]
IMPACT: [one sentence]
FIX: [one sentence]
---

CONVERSION_LEAKS:
FINDING: [specific finding]
SEVERITY: [High/Medium/Low]
IMPACT: [one sentence]
FIX: [one sentence]
---

FOLLOW_UP_LEAKS:
FINDING: [specific finding]
SEVERITY: [High/Medium/Low]
IMPACT: [one sentence]
FIX: [one sentence]
---

PRIORITY_FIXES:
1. [Most critical fix]
2. [Second most critical]
3. [Third most critical]

LEAK_COUNT:
Lead Leaks: [number]
Conversion Leaks: [number]
Follow-Up Leaks: [number]
Total: [number]
```

---

## Code Rules

- Keep app.py under 80 lines — all logic lives in tools/
- Each tool is a standalone Python file with one main function
- Every function has a docstring
- No global state
- Use pathlib for all file paths
- requirements.txt must pin exact versions

---

## What NOT to Build in Phase 1

- No PDF generation
- No email sending
- No user accounts or login
- No database
- No multi-page scraping (homepage only)