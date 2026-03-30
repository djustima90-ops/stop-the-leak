"""Stop the Leak — Flask app tying the audit pipeline together."""

from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, render_template, request

from tools.scrape_site import scrape_site
from tools.extract_content import extract_content
from tools.call_claude import call_claude
from tools.generate_report import generate_report
from tools.save_output import save_output

app = Flask(__name__)


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
    analysis = call_claude(content)

    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    report_html = generate_report(analysis, business_name, url, timestamp)
    save_output(report_html, business_name)

    return report_html


if __name__ == "__main__":
    app.run(debug=True, port=5001)
