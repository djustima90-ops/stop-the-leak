"""Stop the Leak — Flask app tying the audit pipeline together."""

import csv
import ipaddress
import os
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests as http_requests
import resend
from dotenv import load_dotenv

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from tools.scrape_site import scrape_site
from tools.extract_content import extract_content
from tools.extract_brand import extract_brand
from tools.detect_industry import detect_industry
from tools.call_claude import call_claude
from tools.generate_report import generate_report
from tools.save_output import save_output

load_dotenv()
resend.api_key = os.getenv("RESEND_API_KEY")

app = Flask(__name__)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["10 per hour"],
    storage_uri="memory://",
)

LEADS_CSV = Path(__file__).resolve().parent / "leads.csv"
REPORTS_DIR = Path("/tmp/reports")
REPORTS_DIR.mkdir(exist_ok=True)


@app.route("/")
def index():
    """Serve the homepage with the URL input form."""
    return render_template("index.html")


def _error_page(title, message, details=""):
    """Return a styled, on-brand error page."""
    detail_html = f'<p style="color:#94a3b8;font-size:0.95rem;line-height:1.7;white-space:pre-line;">{details}</p>' if details else ""
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '<title>Error — Stop the Leak</title>'
        '<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;'
        'background:#09101d;color:#e2e8f0;display:flex;align-items:center;justify-content:center;'
        'min-height:100vh;margin:0;text-align:center;padding:2rem;}'
        '.wrap{max-width:520px}'
        '.title{font-size:1.8rem;font-weight:800;margin-bottom:1rem;}'
        '.title span{color:#ef4444}'
        'p{color:#94a3b8;line-height:1.7;margin-bottom:1.5rem;}'
        'ul{text-align:left;display:inline-block;color:#94a3b8;line-height:2;margin-bottom:2rem;padding-left:1.2rem;}'
        'a{display:inline-block;background:#dc2626;color:#fff;padding:0.8rem 2rem;'
        'border-radius:8px;text-decoration:none;font-weight:700;}'
        'a:hover{background:#ef4444}</style></head>'
        f'<body><div class="wrap">'
        f'<div class="title"><span>{title}</span></div>'
        f'<p>{message}</p>'
        f'{detail_html}'
        f'<a href="/">&larr; Try Again</a>'
        f'</div></body></html>'
    )


@app.route("/audit", methods=["POST"])
@limiter.limit("10 per hour")
def audit():
    """Run the full leak audit pipeline and return the report."""
    try:
        url = request.form["url"].strip()

        # URL normalization: allow bare domains like "facebook.com"
        if not url.startswith("http://") and not url.startswith("https://"):
            if url.startswith("www."):
                url = "https://" + url
            else:
                url = "https://" + url

        # Input validation
        if len(url) > 500:
            return _error_page(
                "That URL doesn't look like a public website.",
                "Please enter a valid business URL.",
            ), 400

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return _error_page(
                "That URL doesn't look like a public website.",
                "Please enter a valid business URL.",
            ), 400

        hostname = parsed.hostname or ""
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", ""):
            return _error_page(
                "That URL doesn't look like a public website.",
                "Please enter a valid business URL.",
            ), 400

        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_reserved:
                return _error_page(
                    "That URL doesn't look like a public website.",
                    "Please enter a valid business URL.",
                ), 400
        except ValueError:
            pass  # hostname is not an IP — that's fine

        # Strip query parameters and fragments
        url = parsed._replace(query="", fragment="").geturl()

        # Try https first, fall back to http
        try:
            http_requests.head(url, timeout=5, allow_redirects=True)
        except Exception:
            if url.startswith("https://"):
                url = "http://" + url[8:]

        business_name = request.form.get("business_name", "").strip()
        if not business_name:
            business_name = urlparse(url).netloc

        try:
            html = scrape_site(url)
        except (ConnectionError, http_requests.exceptions.ConnectionError,
                http_requests.exceptions.Timeout,
                http_requests.exceptions.MissingSchema) as e:
            print(f"[Audit] Scrape failed for {url}: {e}")
            return _error_page(
                "We couldn't reach that website.",
                "This usually means:",
                details=(
                    '<ul>'
                    '<li>The URL may be misspelled</li>'
                    '<li>The website is currently down</li>'
                    '<li>The site is blocking automated requests</li>'
                    '</ul>'
                    '<p style="color:#64748b;font-size:0.85rem;">Please check the URL and try again.</p>'
                ),
            ), 502
        except Exception as e:
            print(f"[Audit] Scrape error for {url}: {e}")
            return _error_page(
                "We couldn't reach that website.",
                "This usually means:",
                details=(
                    '<ul>'
                    '<li>The URL may be misspelled</li>'
                    '<li>The website is currently down</li>'
                    '<li>The site is blocking automated requests</li>'
                    '</ul>'
                    '<p style="color:#64748b;font-size:0.85rem;">Please check the URL and try again.</p>'
                ),
            ), 502

        content = extract_content(html, url)
        brand = extract_brand(url)
        industry = detect_industry(content)
        analysis = call_claude(content, industry)

        timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        report_html = generate_report(
            analysis, business_name, url, timestamp, industry, brand,
        )
        save_output(report_html, business_name)

        # Save to a temp file so the report survives page reload
        report_id = uuid.uuid4().hex[:12]
        report_file = REPORTS_DIR / f"{report_id}.html"
        report_file.write_text(report_html, encoding="utf-8")

        return redirect(url_for("view_report", report_id=report_id))

    except Exception as e:
        print(f"[Audit] Unexpected error: {e}")
        return _error_page(
            "Something went wrong.",
            "An unexpected error occurred while generating your report. "
            "Please try again in a moment.",
        ), 500


@app.route("/report/<report_id>")
def view_report(report_id):
    """Serve a previously generated report by ID."""
    # Sanitize: only allow hex characters
    if not all(c in "0123456789abcdef" for c in report_id):
        return "Invalid report ID", 400
    report_file = REPORTS_DIR / f"{report_id}.html"
    if not report_file.exists():
        return _error_page(
            "Report expired.",
            "This report is no longer available. Reports are temporary "
            "and expire when the server recycles.",
            details='<p style="color:#64748b;font-size:0.85rem;">Run a new audit to generate a fresh report.</p>',
        ), 404
    return report_file.read_text(encoding="utf-8")


@app.route("/capture-email", methods=["POST"])
@limiter.limit("5 per hour")
def capture_email():
    """Save lead to CSV and send emails via Resend."""
    data = request.get_json(force=True)
    email = data.get("email", "").strip()
    if not email:
        return jsonify({"error": "email required"}), 400

    business_name = data.get("business_name", "Unknown")
    url = data.get("url", "")
    domain = data.get("domain", urlparse(url).netloc if url else "")
    monthly_loss = data.get("monthly_loss", 0)
    annual_loss = data.get("annual_loss", 0)
    top_leaks = data.get("top_leaks", [])
    now = datetime.now()

    # Always save to CSV first
    write_header = not LEADS_CSV.exists()
    with open(LEADS_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(
                ["timestamp", "email", "business_name", "url",
                 "monthly_loss", "annual_loss"]
            )
        writer.writerow([
            now.isoformat(), email, business_name, url,
            monthly_loss, annual_loss,
        ])

    # Send emails via Resend (non-blocking — failures don't affect response)
    try:
        _send_owner_email(email, business_name, domain, top_leaks,
                          monthly_loss, annual_loss)
    except Exception as e:
        print(f"[Resend] Owner email failed: {e}")

    try:
        _send_notification_email(business_name, url, email, domain,
                                 monthly_loss, annual_loss, now)
    except Exception as e:
        print(f"[Resend] Notification email failed: {e}")

    return jsonify({"ok": True})


def _send_owner_email(to_email, business_name, domain, top_leaks,
                      monthly_loss, annual_loss):
    """Send the leak report email to the business owner."""
    leak_bullets = ""
    for leak in top_leaks[:3]:
        finding = leak.get("finding", "")
        loss = leak.get("monthly_loss", 0)
        leak_bullets += f"""
        <tr>
          <td style="padding:12px 20px;border-bottom:1px solid #1e293b;color:#e2e8f0;font-size:15px;">
            <span style="color:#ef4444;font-weight:600;">&#x25CF;</span>&nbsp; {finding}
            <span style="float:right;color:#ef4444;font-weight:700;">-${loss:,}/mo</span>
          </td>
        </tr>"""

    html_body = f"""
    <div style="background:#0a0a0a;padding:0;margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto;background:#0f0f0f;border:1px solid #1e293b;">
        <tr>
          <td style="padding:32px 24px 24px;text-align:center;border-bottom:1px solid #1e293b;">
            <span style="font-size:28px;font-weight:800;letter-spacing:-0.5px;">
              <span style="color:#ef4444;">Stop</span><span style="color:#ffffff;"> the </span><span style="color:#ef4444;">Leak</span>
            </span>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 24px 16px;">
            <p style="color:#94a3b8;font-size:15px;margin:0 0 4px;">Here's what we found on</p>
            <p style="color:#ffffff;font-size:20px;font-weight:700;margin:0 0 24px;">{domain}</p>
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;border:1px solid #1e293b;border-radius:8px;overflow:hidden;">
              <tr>
                <td style="padding:16px 20px;color:#94a3b8;font-size:13px;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #1e293b;font-weight:600;">
                  Top Leaks Found
                </td>
              </tr>
              {leak_bullets}
            </table>
          </td>
        </tr>
        <tr>
          <td style="padding:24px;text-align:center;">
            <div style="background:linear-gradient(135deg,#1a0000,#0f0f0f);border:1px solid #ef4444;border-radius:12px;padding:28px;">
              <p style="color:#94a3b8;font-size:13px;margin:0 0 8px;text-transform:uppercase;letter-spacing:1px;">Estimated Monthly Loss</p>
              <p style="color:#ef4444;font-size:42px;font-weight:800;margin:0;letter-spacing:-1px;">${monthly_loss:,}/mo</p>
              <p style="color:#94a3b8;font-size:16px;margin:8px 0 0;">That's <strong style="color:#ef4444;">${annual_loss:,}/year</strong> walking out the door</p>
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 24px 32px;text-align:center;">
            <a href="https://calendly.com/djustima90/30min"
               style="display:inline-block;background:#ef4444;color:#ffffff;font-size:16px;font-weight:700;padding:16px 40px;border-radius:8px;text-decoration:none;letter-spacing:0.3px;">
              Book a Free Call to Fix This
            </a>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 24px;border-top:1px solid #1e293b;text-align:center;">
            <p style="color:#475569;font-size:12px;margin:0;">Built by David Justima &nbsp;|&nbsp; hello@stoptheleak.com</p>
          </td>
        </tr>
      </table>
    </div>"""

    resend.Emails.send({
        "from": "onboarding@resend.dev",
        "to": [to_email],
        "subject": f"Your Website Leak Report — {business_name}",
        "html": html_body,
    })


def _send_notification_email(business_name, url, lead_email, domain,
                             monthly_loss, annual_loss, timestamp):
    """Send lead notification to David."""
    body = f"""New lead captured from Stop the Leak:

Business: {business_name}
URL: {url}
Domain: {domain}
Email: {lead_email}
Monthly Loss: ${monthly_loss:,}
Annual Loss: ${annual_loss:,}
Timestamp: {timestamp.strftime('%B %d, %Y at %I:%M %p')}

View their report at: {url}
"""

    resend.Emails.send({
        "from": "onboarding@resend.dev",
        "to": ["djustima90@gmail.com"],
        "subject": f"\U0001f534 New Lead: {business_name} — ${monthly_loss:,}/month identified",
        "text": body,
    })


@app.errorhandler(429)
def ratelimit_handler(e):
    """Friendly page when rate limit is exceeded."""
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '<title>Rate Limit — Stop the Leak</title>'
        '<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;'
        'background:#09101d;color:#e2e8f0;display:flex;align-items:center;justify-content:center;'
        'min-height:100vh;margin:0;text-align:center;padding:2rem;}'
        '.wrap{max-width:480px}.title{font-size:2rem;font-weight:800;margin-bottom:1rem;}'
        '.title span{color:#ef4444}p{color:#94a3b8;line-height:1.6;margin-bottom:2rem;}'
        'a{display:inline-block;background:#dc2626;color:#fff;padding:0.8rem 2rem;'
        'border-radius:8px;text-decoration:none;font-weight:700;}'
        'a:hover{background:#ef4444}</style></head>'
        '<body><div class="wrap">'
        '<div class="title">Slow <span>Down</span></div>'
        "<p>You've run too many audits. Please wait an hour and try again.</p>"
        '<a href="/">Back to Home</a>'
        '</div></body></html>',
        429,
    )


@app.route("/health")
def health():
    """Return env var status for debugging (values hidden)."""
    keys = ["RESEND_API_KEY", "ANTHROPIC_API_KEY"]
    status = {k: bool(os.getenv(k)) for k in keys}
    return jsonify({"env": status})


@app.route("/website")
def website():
    """Serve the marketing landing page."""
    return render_template("website/index.html")


@app.route("/sitemap.xml")
def sitemap():
    """Serve the sitemap."""
    return send_from_directory("static", "sitemap.xml", mimetype="application/xml")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
