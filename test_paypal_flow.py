"""Exercises paypal.send_requests against a local fake of the PayPal sandbox endpoints.

This checks OUR request flow (token -> create invoice -> send). It does not prove PayPal's
live schema; test with real sandbox credentials for that (see README).
"""

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CALLS = []
RECIPIENT = {}  # invoice path -> recipient email


class FakePayPal(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n).decode()
        CALLS.append((self.path, self.headers.get("authorization", ""), raw))
        base = f"http://127.0.0.1:{self.server.server_port}"
        if self.path == "/v1/oauth2/token":
            out, code = {"access_token": "TOKEN123"}, 200
        elif self.path == "/v2/invoicing/invoices":
            inv = f"/v2/invoicing/invoices/INV2-{len(CALLS)}"
            RECIPIENT[inv] = json.loads(raw)["primary_recipients"][0]["billing_info"]["email_address"]
            out, code = {"rel": "x", "href": f"{base}{inv}", "method": "GET"}, 201
        elif self.path.endswith("/send"):
            inv = self.path[: -len("/send")]
            if "india" in RECIPIENT.get(inv, ""):
                out, code = {"name": "MEDIA_TYPE_NOT_ACCEPTABLE", "details": [{"issue": "INR_FOREIGN_CURRENCY_BLOCKED",
                             "description": "PayPal is unable to send invoices to customers within India."}]}, 406
            else:
                out, code = {"href": f"{base}/invoice/p/#ABC"}, 200
        else:
            out, code = {"error": "nope"}, 404
        body = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        CALLS.append(("DELETE " + self.path, self.headers.get("authorization", ""), ""))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


class PayPalFlow(unittest.TestCase):
    def test_sends_one_invoice_per_person_with_emails(self):
        srv = HTTPServer(("127.0.0.1", 0), FakePayPal)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ.update(
            PAYPAL_CLIENT_ID="id", PAYPAL_CLIENT_SECRET="secret",
            PAYPAL_BASE_URL=f"http://127.0.0.1:{srv.server_port}",
        )
        import paypal
        paypal.BASE = os.environ["PAYPAL_BASE_URL"]

        shares = {
            "Me": {"items": [{"name": "Soda", "cents": 200}], "tax_cents": 0, "tip_cents": 0, "total_cents": 200},
            "Asha": {"items": [{"name": "Pizza", "cents": 1400}], "tax_cents": 140, "tip_cents": 0, "total_cents": 1540},
            "Ravi": {"items": [{"name": "Burger", "cents": 1250}], "tax_cents": 125, "tip_cents": 300, "total_cents": 1675},
            "NoEmail": {"items": [{"name": "Tea", "cents": 300}], "tax_cents": 0, "tip_cents": 0, "total_cents": 300},
            "Dotty": {"items": [{"name": "Tea", "cents": 300}], "tax_cents": 0, "tip_cents": 0, "total_cents": 300},
            "Typo": {"items": [{"name": "Tea", "cents": 300}], "tax_cents": 0, "tip_cents": 0, "total_cents": 300},
            "Indian": {"items": [{"name": "Tea", "cents": 300}], "tax_cents": 0, "tip_cents": 0, "total_cents": 300},
        }
        people = [
            {"name": "Me", "email": "me@example.com"},  # first person = payer, never invoiced
            {"name": "Asha", "email": "asha@example.com"},
            {"name": "Ravi", "email": "ravi@example.com"},
            {"name": "NoEmail", "email": ""},
            {"name": "Dotty", "email": " dotty@example.com. "},
            {"name": "Typo", "email": "not-an-email"},
            {"name": "Indian", "email": "buyer@india.example.com"},
        ]
        rows = paypal.send_requests(shares, people, "Demo Bistro", "USD", "thanks!")
        srv.shutdown()

        by = {r["name"]: r for r in rows}
        self.assertEqual(by["Me"]["status"], "payer")
        self.assertNotIn("me@example.com", RECIPIENT.values())
        self.assertEqual(by["Asha"]["status"], "sent")
        self.assertEqual(by["Ravi"]["status"], "sent")
        self.assertEqual(by["NoEmail"]["status"], "skipped")
        self.assertEqual(by["Typo"]["status"], "skipped")        # invalid email never reaches PayPal
        self.assertEqual(by["Dotty"]["status"], "sent")          # trailing dot/space cleaned up
        self.assertEqual(by["Indian"]["status"], "error")
        self.assertIn("NOT India", by["Indian"]["detail"])        # friendly hint shown
        self.assertTrue(any(c[0].startswith("DELETE ") for c in CALLS))  # unsent draft removed
        self.assertIn("dotty@example.com", RECIPIENT.values())

        token_call = CALLS[0]
        self.assertTrue(token_call[1].startswith("Basic "))
        creates = [c for c in CALLS if c[0] == "/v2/invoicing/invoices"]
        self.assertEqual(len(creates), 4)
        self.assertTrue(all(c[1] == "Bearer TOKEN123" for c in creates))
        payload = json.loads(creates[1][2])
        self.assertEqual(payload["primary_recipients"][0]["billing_info"]["email_address"], "ravi@example.com")
        names = [i["name"] for i in payload["items"]]
        self.assertEqual(names, ["Burger", "Tax share", "Tip share"])
        self.assertEqual(sum(1 for c in CALLS if c[0].endswith("/send")), 4)


class DemoMode(unittest.TestCase):
    def test_payer_labelled_without_credentials(self):
        saved = {k: os.environ.pop(k, None) for k in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET")}
        try:
            import paypal
            shares = {
                "Me": {"items": [], "tax_cents": 0, "tip_cents": 0, "total_cents": 500},
                "Bo": {"items": [], "tax_cents": 0, "tip_cents": 0, "total_cents": 700},
            }
            rows = paypal.send_requests(shares, [{"name": "Me", "email": ""}, {"name": "Bo", "email": "b@x.com"}], "", "USD", "")
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
        self.assertEqual([r["status"] for r in rows], ["payer", "demo"])


if __name__ == "__main__":
    unittest.main()
