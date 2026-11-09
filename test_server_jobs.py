"""Receipt reading runs as a background job the page polls; check that flow end to end."""

import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def call(base, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


class Jobs(unittest.TestCase):
    def setUp(self):
        for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
            os.environ.pop(k, None)
        import server
        self.server = server
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def wait(self, job):
        for _ in range(50):
            code, j = call(self.base, "/api/job/" + job)
            if j.get("status") != "pending":
                return code, j
            time.sleep(0.05)
        self.fail("job never finished")

    def test_parse_receipt_job_completes(self):
        code, r = call(self.base, "/api/parse-receipt", {"image": "QUJD"})
        self.assertEqual(code, 202)
        _, j = self.wait(r["job"])
        self.assertEqual(j["status"], "done")
        self.assertEqual(len(j["result"]["items"]), 5)  # demo receipt when no AI key

    def test_failed_job_reports_error(self):
        import ai
        orig = ai.parse_receipt
        ai.parse_receipt = lambda *a: (_ for _ in ()).throw(RuntimeError("Gemini API error 429: quota"))
        try:
            _, r = call(self.base, "/api/parse-receipt", {"image": "QUJD"})
            _, j = self.wait(r["job"])
        finally:
            ai.parse_receipt = orig
        self.assertEqual(j["status"], "error")
        self.assertIn("429", j["error"])

    def test_unknown_job_404(self):
        code, _ = call(self.base, "/api/job/nope")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
