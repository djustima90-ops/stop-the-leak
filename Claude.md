# Stop the Leak — CLAUDE.md

## What This Project Is
Stop the Leak is an AI-powered website revenue audit tool built by David Justima.
A business owner pastes their URL. The app scrapes their site, analyzes it with
Claude, and returns a personalized report showing exactly how much revenue their
website is losing per month — in dollars — with a letter grade and action plan.

Live: stop-the-leak.vercel.app
Local: port 5001
GitHub: github.com/djustima90-ops/stop-the-leak

## Stack
- Python 3.9, Flask
- Anthropic SDK (claude-sonnet) — primary AI model
- BeautifulSoup4 — scraping (being replaced by Firecrawl)
- Resend — email automation
- Flask-Limiter — rate limiting
- Supabase — database (leads table, reports table)
- Sentry — error tracking
- Deployed on Vercel (migrating to Railway in Month 2)

## Pipeline
URL input → scrape_site → extract_content → extract_brand →
detect_industry → call_claude → generate_report → save to Supabase → /report/[uuid]

## File Structure
app.py                    — Flask app, all routes
CLAUDE.md                 — this file
requirements.txt
.env                      — ANTHROPIC_API_KEY, RESEND_API_KEY, SUPABASE_URL,
                            SUPABASE_KEY, SENTRY_DSN (never commit)
leads.csv                 — DEPRECATED, migrated to Supabase
data/industries.json      — 20+ industry profiles with revenue benchmarks
workflows/leak_audit.md   — master audit prompt
tools/
  scrape_site.py          — fetches raw HTML (Firecrawl replacing this)
  extract_content.py      — BeautifulSoup parser
  extract_brand.py        — favicon/color/logo extraction (3s timeout required)
  detect_industry.py      — keyword-based industry classifier
  call_claude.py          — Claude API call (MUST use tool_use for JSON output)
  generate_report.py      — Jinja2 report renderer
  save_output.py          — saves to Supabase reports table
templates/
  index.html              — landing page + loading screen
  report.html             — full audit report
  website/index.html      — marketing site
static/
  cha-ching.mp3

## Critical Rules — Always Follow These

### 1. Claude Output Must Be Structured JSON
NEVER ask Claude to return prose and parse it manually.
ALWAYS use tool_use with a strict schema:
{
  executive_summary: string,
  grade: "A"|"B"|"C"|"D"|"F",
  findings: [{
    title: string,
    category: "Lead Leak"|"Conversion Leak"|"Follow-Up Leak",
    severity: "HIGH"|"MEDIUM"|"LOW",
    monthly_loss: number,
    impact: string,
    fix: string
  }]
}

### 2. Every Claude API Call Must Have Error Handling
NEVER make a bare call_claude() without a try/except wrapper.
Pattern to always use:
try:
    result = call_claude(content, industry)
except anthropic.APITimeoutError:
    return render_template("error.html", msg="Audit timed out. Try again.")
except anthropic.RateLimitError:
    time.sleep(60)
    result = call_claude(content, industry)
except Exception as e:
    log_error(url, str(e))
    return render_template("error.html", msg="Something went wrong.")

### 3. URL Validation — Always Validate Before Scraping
Block: localhost, 127.0.0.1, 192.168.x.x, file://, javascript:, data:
Require: http:// or https:// scheme, valid TLD, non-empty hostname
Add 10-second timeout on all scraper requests

### 4. Brand Extraction Is Non-Blocking
extract_brand() MUST run inside a ThreadPoolExecutor with a 3-second timeout.
If it fails or times out, continue with brand = {} gracefully. Never let it
block the audit pipeline.

### 5. All Data Goes to Supabase
leads.csv is DEPRECATED. Never write to it.
All leads → Supabase leads table
All reports → Supabase reports table (uuid, html, business_name, url, grade, created_at)
Reports served from Supabase on /report/[uuid] — never from /tmp

### 6. Parallel Pipeline
extract_brand() and detect_industry() have no dependency on each other.
Run them simultaneously using concurrent.futures.ThreadPoolExecutor.
Never run them sequentially.

## Design Standards — Non-Negotiable
- NO Inter font, NO Roboto, NO Arial
- NO generic purple gradients
- NO card layouts that look like Tailwind tutorials
- Dark, bold, editorial aesthetic
- Fonts: Clash Display or Syne for headings, Space Grotesk or DM Sans for body
- Primary accent: #dc2626 red (unless brand color extracted)
- Every page must feel premium — not AI slop
- Mobile-first — reports must work on phone

## Copy and Tone Standards
- Lead with dollar amounts: "You're losing $4,200/month" not "Your site has issues"
- First-person David voice: trusted local advisor, not a SaaS startup
- Berkshires specific: seasonal visitors, walk-in traffic, repeat clients
- CTA is always "Book a Free Call" — never "Contact Us" or "Learn More"
- Executive summaries must name the business, reference their vertical,
  include one location-specific detail when available

## Business Context
Target: Local SMBs — restaurants, contractors, salons, medical, law/CPA, retail
Market: Berkshires MA and surrounding region
Pricing: Free audit → $500 fix top 3 leaks → $1,500 full package
Warm leads: Alignable connections — Lucille Murray (145 connections, Berkshires
  gateway) and Lauren Fritscher (Berkshire Muse, already invited David)
Calendly: https://calendly.com/djustima90/30min
Domain: stoptheleak.com (buy this)
Goal: 1 paying client before April 27, 2026

## What Good Looks Like
Every new feature must pass this checklist:
☐ Claude output is structured JSON via tool_use
☐ Every AI call has try/except with graceful error page
☐ No blocking operations without timeout caps
☐ Data persists to Supabase, not CSV or /tmp
☐ UI matches design standards (no AI slop)
☐ Copy leads with dollar amounts
☐ Works on mobile
