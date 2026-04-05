"""Stop the Leak — Flask app tying the audit pipeline together."""

import concurrent.futures
import ipaddress
import os
import time
import traceback
from datetime import datetime
from urllib.parse import urlparse

import anthropic
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
from tools.supabase_client import get_supabase

load_dotenv()
resend.api_key = os.getenv("RESEND_API_KEY")

# ── Sentry init (optional — app starts normally without it) ──────────────
try:
    import sentry_sdk
    sentry_dsn = os.getenv("SENTRY_DSN")
    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        print("[Sentry] Initialized")
except Exception as e:
    print(f"[Sentry] Failed to initialize: {e}")

app = Flask(__name__)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["10 per hour"],
    storage_uri="memory://",
)


# ── URL validation ───────────────────────────────────────────────────────

_BLOCKED_HOSTNAMES = {"localhost", "0.0.0.0", ""}
_BLOCKED_SCHEMES = {"file", "javascript", "data", "ftp"}


def validate_url(url: str) -> tuple[bool, str]:
    """Validate a user-submitted URL.

    Blocks: localhost, 127.0.0.1, 192.168.x.x, 10.x.x.x, file://, javascript:,
            data:, and any private / loopback / reserved IP.
    Requires: http(s) scheme, non-empty hostname, a real TLD.

    Returns:
        (is_valid, error_message). error_message is "" when valid.
    """
    if not url or not isinstance(url, str):
        return False, "Please enter a URL."
    url = url.strip()
    if len(url) > 500:
        return False, "That URL is too long."

    # Reject dangerous schemes before urlparse (javascript:, data:, file:)
    lowered = url.lower()
    for bad in _BLOCKED_SCHEMES:
        if lowered.startswith(f"{bad}:"):
            return False, "That URL doesn't look like a public website."

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "URL must start with http:// or https://"

    hostname = (parsed.hostname or "").lower()
    if not hostname or hostname in _BLOCKED_HOSTNAMES:
        return False, "That URL doesn't look like a public website."

    # Block private/loopback/reserved IPs (covers 127.0.0.1, 192.168.x.x, 10.x.x.x)
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            return False, "That URL doesn't look like a public website."
    except ValueError:
        # Not an IP — must be a hostname with a TLD
        if "." not in hostname:
            return False, "That URL doesn't look like a public website."
        tld = hostname.rsplit(".", 1)[-1]
        if not tld or len(tld) < 2 or not tld.isalpha():
            return False, "That URL doesn't look like a public website."

    return True, ""


@app.route("/")
def index():
    """Serve the homepage with the URL input form."""
    return render_template("index.html")


def _error_page(message: str, status: int = 400):
    """Render the standard error template."""
    return render_template("error.html", msg=message), status


def _log_audit(url: str, industry_name: str, grade: str,
               duration_seconds: float, success: bool, error_message: str = "") -> str:
    """Insert one row into the Supabase audit_log table. Never raises.

    Returns a status string: "ok", "error: <detail>". Callers can log or
    return this; by contract this function still never raises.
    """
    import sys
    print(
        f"[audit_log] fired url={url!r} industry={industry_name!r} grade={grade!r} "
        f"duration={duration_seconds:.2f}s success={success} err={error_message!r}",
        flush=True, file=sys.stderr,
    )
    try:
        client = get_supabase()
        resp = client.table("audit_log").insert({
            "url": url or "",
            "industry": industry_name or "",
            "grade": grade or "",
            "duration_seconds": round(duration_seconds, 2),
            "success": bool(success),
            "error_message": (error_message or "")[:1000],
        }).execute()
        rows = len(resp.data or [])
        print(f"[audit_log] insert OK rows={rows}", flush=True, file=sys.stderr)
        return "ok" if rows else "error: no rows returned"
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        print(f"[audit_log] INSERT FAILED: {detail}", flush=True, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        return f"error: {detail}"


@app.route("/audit", methods=["POST"])
@limiter.limit("10 per hour")
def audit():
    """Run the full leak audit pipeline and return the report."""
    start = time.time()
    url = ""
    industry_name = ""
    grade = ""
    success = False
    error_message = ""

    try:
        url = request.form["url"].strip()

        # Allow bare domains like "facebook.com"
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        # URL validation — blocks localhost, private IPs, bad schemes, etc.
        is_valid, err = validate_url(url)
        if not is_valid:
            error_message = f"invalid_url: {err}"
            return _error_page(err, 400)

        parsed = urlparse(url)
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
        except Exception as e:
            print(f"[Audit] Scrape failed for {url}: {e}")
            error_message = f"scrape_failed: {type(e).__name__}: {e}"
            if "403" in str(e):
                return _error_page(
                    "This website is blocking automated access. Try a different URL.",
                    403,
                )
            return _error_page(
                "We couldn't reach that website. Please check the URL and try again.",
                502,
            )

        content = extract_content(html, url)

        # Parallel pipeline: brand extraction and industry detection are
        # independent — run them simultaneously.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            brand_future = executor.submit(extract_brand, url)
            industry_future = executor.submit(detect_industry, content)
            brand = brand_future.result() or {}
            industry = industry_future.result()
        industry_name = (industry or {}).get("name", "")

        # Claude API call with typed error handling
        try:
            analysis = call_claude(content, industry)
        except anthropic.APITimeoutError:
            error_message = "claude_timeout"
            return _error_page("Audit timed out. Please try again.", 504)
        except anthropic.RateLimitError:
            time.sleep(60)
            try:
                analysis = call_claude(content, industry)
            except Exception as e:
                print(f"[Audit] Claude retry failed: {type(e).__name__}: {e}")
                error_message = f"claude_retry_failed: {type(e).__name__}: {e}"
                return _error_page("Something went wrong.", 500)
        except anthropic.APIError as e:
            print(f"[Audit] Claude API error: {type(e).__name__}: {e}")
            error_message = f"claude_api_error: {type(e).__name__}: {e}"
            return _error_page("Something went wrong.", 500)

        timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        report_html = generate_report(
            analysis, business_name, url, timestamp, industry, brand,
        )

        grade = (analysis or {}).get("grade", "") if isinstance(analysis, dict) else ""
        report_id = save_output(report_html, business_name, url=url, grade=grade)

        success = True
        return redirect(url_for("view_report", report_id=report_id))

    except Exception as e:
        print(f"[Audit] Unexpected error: {type(e).__name__}: {e}")
        traceback.print_exc()
        error_message = f"unexpected: {type(e).__name__}: {e}"
        return _error_page(
            "An unexpected error occurred while generating your report. Please try again.",
            500,
        )
    finally:
        _log_audit(
            url=url,
            industry_name=industry_name,
            grade=grade,
            duration_seconds=time.time() - start,
            success=success,
            error_message=error_message,
        )


@app.route("/report/<report_id>")
def view_report(report_id):
    """Serve a previously generated report by uuid from Supabase."""
    # Sanitize: allow standard uuid characters only
    if not all(c in "0123456789abcdef-" for c in report_id.lower()) or len(report_id) > 64:
        return "Invalid report ID", 400

    try:
        client = get_supabase()
        response = (
            client.table("reports")
            .select("html")
            .eq("id", report_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
    except Exception as e:
        print(f"[view_report] Supabase error: {type(e).__name__}: {e}")
        return _error_page("We couldn't load that report. Please try again.", 500)

    if not rows:
        return _error_page(
            "That report could not be found. Run a new audit to generate a fresh report.",
            404,
        )
    return rows[0]["html"]


@app.route("/capture-email", methods=["POST"])
@limiter.limit("5 per hour")
def capture_email():
    """Save lead to Supabase leads table and send emails via Resend."""
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

    # Persist lead to Supabase (leads.csv is deprecated)
    try:
        client = get_supabase()
        client.table("leads").insert({
            "email": email,
            "business_name": business_name,
            "url": url,
            "monthly_loss": monthly_loss,
            "annual_loss": annual_loss,
        }).execute()
    except Exception as e:
        print(f"[capture_email] Supabase insert failed: {type(e).__name__}: {e}")
        # Don't block email send on storage failure

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


@app.route("/setup-db")
def setup_db():
    """Idempotently create the leads and reports tables in Supabase.

    Uses Supabase's REST RPC to run SQL. Assumes a `exec_sql` RPC or the
    Postgres-direct connection is available. When running against a plain
    Supabase project the recommended path is to run this SQL once in the
    SQL editor; this route attempts it via RPC and reports status.
    """
    sql = """
    create table if not exists leads (
      id uuid primary key default gen_random_uuid(),
      created_at timestamptz not null default now(),
      email text,
      business_name text,
      url text,
      monthly_loss numeric,
      annual_loss numeric
    );

    create table if not exists reports (
      id uuid primary key default gen_random_uuid(),
      created_at timestamptz not null default now(),
      business_name text,
      url text,
      grade text,
      html text
    );

    create table if not exists audit_log (
      id uuid primary key default gen_random_uuid(),
      created_at timestamptz not null default now(),
      url text,
      industry text,
      grade text,
      duration_seconds numeric,
      success boolean,
      error_message text
    );
    """.strip()

    try:
        client = get_supabase()
        # Try an `exec_sql` RPC if the project has it defined
        client.rpc("exec_sql", {"sql": sql}).execute()
        return jsonify({"ok": True, "message": "Tables created or already exist."})
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "sql": sql,
            "hint": (
                "If the RPC is not available, paste the SQL above into the "
                "Supabase SQL editor and run it once."
            ),
        }), 500


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
    return render_template(
        "error.html",
        msg="You've run too many audits. Please wait an hour and try again.",
    ), 429


@app.route("/test-log")
def test_log():
    """Directly exercise _log_audit with dummy data and return the result."""
    status = _log_audit(
        url="https://test.example.com",
        industry_name="test_industry",
        grade="A",
        duration_seconds=1.23,
        success=True,
        error_message="test-log route dummy call",
    )
    return jsonify({"status": status, "ok": status == "ok"}), (200 if status == "ok" else 500)


@app.route("/health")
def health():
    """Return env var status for debugging (values hidden)."""
    keys = ["RESEND_API_KEY", "ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_KEY", "SENTRY_DSN", "FIRECRAWL_API_KEY"]
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
