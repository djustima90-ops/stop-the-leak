"""Basic tests for the Stop the Leak Flask app."""

import unittest
from unittest.mock import patch

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app


class TestApp(unittest.TestCase):

    def setUp(self):
        app.config["TESTING"] = True
        # Disable rate limiting in tests
        app.config["RATELIMIT_ENABLED"] = False
        self.client = app.test_client()

    def test_index_loads(self):
        """GET / returns 200."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Stop the Leak", resp.data)

    def test_audit_requires_url(self):
        """POST /audit with no URL returns error, not crash."""
        resp = self.client.post("/audit", data={})
        self.assertIn(resp.status_code, (400, 500))
        # Should return HTML, not a raw traceback
        self.assertIn(b"<", resp.data)

    def test_audit_bad_url(self):
        """POST /audit with garbage URL returns error page, not crash."""
        resp = self.client.post("/audit", data={"url": "notawebsite!@#"})
        self.assertIn(resp.status_code, (400, 404, 500, 502))
        # Should return HTML error page
        self.assertIn(b"<", resp.data)

    def test_health_route(self):
        """GET /health returns JSON with env var status."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("env", data)
        self.assertIn("ANTHROPIC_API_KEY", data["env"])
        self.assertIn("RESEND_API_KEY", data["env"])

    def test_website_route(self):
        """GET /website returns 200."""
        resp = self.client.get("/website")
        self.assertEqual(resp.status_code, 200)

    def test_capture_email_requires_email(self):
        """POST /capture-email with no email returns 400."""
        resp = self.client.post(
            "/capture-email",
            json={"business_name": "Test"},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("error", data)

    def test_report_not_found(self):
        """GET /report/fakeid returns error page, not crash."""
        resp = self.client.get("/report/aabbccddee11")
        self.assertIn(resp.status_code, (404, 400))
        self.assertIn(b"<", resp.data)


if __name__ == "__main__":
    unittest.main()
