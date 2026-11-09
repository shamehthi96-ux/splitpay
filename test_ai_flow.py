"""Checks ai.py's Gemini handling against a local fake Gemini endpoint.

This verifies OUR request shape and parsing; it does not prove Google's live service
accepts it. Try it with a real GEMINI_API_KEY (see README).
"""

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SEEN = []
RECEIPT = {
    "merchant": "Cafe X", "currency": "INR",
    "items": [{"name": "Dosa", "price": 120, "qty": 2}, {"name": "Chai", "price": 40, "qty": 1}],
    "tax": 8, "tip": 0,
}


class FakeGemini(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0)).decode()
        SEEN.append((self.path, self.headers.get("x-goog-api-key"), json.loads(raw)))
        has_image = any("inline_data" in p for p in json.loads(raw)["contents"][0]["parts"])
        text = json.dumps(RECEIPT) if has_image else '```json\n{"1": ["Asha"], "2": ["Asha", "Ghost"]}\n```'
        body = json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class GeminiFlow(unittest.TestCase):
    def test_receipt_and_assignment(self):
        srv = HTTPServer(("127.0.0.1", 0), FakeGemini)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ["GEMINI_API_KEY"] = "KEY123"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        import ai
        ai.GEMINI_BASE = f"http://127.0.0.1:{srv.server_port}/v1beta"
        self.assertEqual(ai.provider(), "gemini")

        rec = ai.parse_receipt("QUJD", "image/jpeg")
        self.assertEqual(rec["currency"], "INR")
        self.assertEqual([i["name"] for i in rec["items"]], ["Dosa", "Chai"])
        self.assertEqual(rec["items"][0]["id"], "1")
        self.assertFalse(rec["demo"])

        path, key, body = SEEN[0]
        self.assertTrue(path.endswith(":generateContent"))
        self.assertEqual(key, "KEY123")
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["contents"][0]["parts"][0]["inline_data"]["data"], "QUJD")

        out = ai.assign_from_text("Asha had everything", rec["items"], ["Asha", "Ravi"], "Asha")
        srv.shutdown()
        self.assertEqual(out, {"1": ["Asha"], "2": ["Asha"]})  # unknown name "Ghost" dropped


if __name__ == "__main__":
    unittest.main()
