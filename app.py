"""Stop the Leak — Flask app tying the audit pipeline together."""

import csv
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request

from tools.scrape_site import scrape_site
from tools.extract_content import extract_content
from tools.extract_brand import extract_brand
from tools.detect_industry import detect_industry
from tools.call_claude import call_claude
from tools.generate_report import generate_report
from tools.save_output import save_output

app = Flask(__name__)

LEADS_CSV = Path(__file__).resolve().parent / "leads.csv"


@app.route("/")
def index():
    """Serve the homepage with the URL input form."""
    return render_template("index.html")


@app.route("/audit", methods=["POST"])
def audit():
    """Run the full leak audit pipeline and return the report."""
    url = request.form["url"].strip()
    business_name = request.form.get("business_name", "").strip()
    if not business_name:
        business_name = urlparse(url).netloc

    html = scrape_site(url)
    content = extract_content(html, url)
    brand = extract_brand(url)
    industry = detect_industry(content)
    analysis = call_claude(content, industry)

    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    report_html = generate_report(
        analysis, business_name, url, timestamp, industry, brand,
    )
    save_output(report_html, business_name)

    return report_html


@app.route("/capture-email", methods=["POST"])
def capture_email():
    """Append lead info to leads.csv."""
    data = request.get_json(force=True)
    email = data.get("email", "").strip()
    if not email:
        return jsonify({"error": "email required"}), 400

    write_header = not LEADS_CSV.exists()
    with open(LEADS_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(
                ["timestamp", "email", "business_name", "url",
                 "monthly_loss", "annual_loss"]
            )
        writer.writerow([
            datetime.now().isoformat(),
            email,
            data.get("business_name", ""),
            data.get("url", ""),
            data.get("monthly_loss", 0),
            data.get("annual_loss", 0),
        ])
    return jsonify({"ok": True})


@app.route("/website")
def website():
    """Serve the marketing landing page."""
    return render_template("website/index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
