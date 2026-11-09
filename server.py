#!/usr/bin/env python3
"""SplitPay: photo of a bill -> AI (Gemini/Claude) reads it -> split by person -> PayPal sandbox invoices.

Standard library only, so it runs anywhere with Python 3.9+:  python3 server.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env(ROOT / ".env")

import ai  # noqa: E402  (needs env loaded first)
import paypal  # noqa: E402
from splitlogic import split_bill  # noqa: E402

MAX_BODY = 12 * 1024 * 1024

# Receipt reading can take a while; run it in the background and let the page poll,
# so slow AI calls never hit a proxy/phone timeout.
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def start_job(fn, *args) -> str:
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with JOBS_LOCK:
        for k in [k for k, j in JOBS.items() if now - j["t"] > 900]:
            del JOBS[k]
        JOBS[job_id] = {"status": "pending", "t": now}

    def run():
        try:
            out = {"status": "done", "result": fn(*args)}
        except Exception as e:
            out = {"status": "error", "error": str(e)}
        with JOBS_LOCK:
            JOBS[job_id].update(out)

    threading.Thread(target=run, daemon=True).start()
    return job_id


class Handler(BaseHTTPRequestHandler):
    server_version = "SplitPay/1.0"

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("content-length") or 0)
        if n > MAX_BODY:
            raise ValueError("Request too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/status":
            return self._json(200, {"ai": ai.ai_enabled(), "paypal": paypal.paypal_enabled(), "model": ai.model_name(), "provider": ai.provider()})
        if path.startswith("/api/job/"):
            with JOBS_LOCK:
                job = JOBS.get(path.rsplit("/", 1)[-1])
                snap = None if job is None else {k: v for k, v in job.items() if k != "t"}
            return self._json(200 if snap else 404, snap or {"error": "unknown job"})
        # Only the page itself is served; source files and .env stay private.
        if path not in ("/", "/index.html"):
            return self._json(404, {"error": "not found"})
        data = (ROOT / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            body = self._read_json()
            route = self.path.split("?")[0]
            if route == "/api/parse-receipt":
                job = start_job(ai.parse_receipt, body.get("image", ""), body.get("media_type", "image/jpeg"))
                return self._json(202, {"job": job})
            if route == "/api/demo-receipt":
                return self._json(200, dict(ai.DEMO_RECEIPT))
            if route == "/api/assign-text":
                people = [p["name"] for p in body["people"]]
                return self._json(
                    200,
                    {"assignments": ai.assign_from_text(body["text"], body["items"], people, body.get("me", ""))},
                )
            if route == "/api/split":
                people = [p["name"] for p in body["people"]]
                return self._json(
                    200,
                    split_bill(body["items"], body["assignments"], people, body.get("tax", 0), body.get("tip", 0)),
                )
            if route == "/api/send-requests":
                people = body["people"]
                result = split_bill(
                    body["items"],
                    body["assignments"],
                    [p["name"] for p in people],
                    body.get("tax", 0),
                    body.get("tip", 0),
                )
                if result["unassigned"]:
                    return self._json(400, {"error": "Some items are not assigned to anyone yet."})
                rows = paypal.send_requests(
                    result["people"], people, body.get("merchant", ""), body.get("currency", "USD"), body.get("note", "")
                )
                return self._json(200, {"results": rows})
            return self._json(404, {"error": "not found"})
        except Exception as e:
            return self._json(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, self.path))


def main():
    port = int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"SplitPay running on http://localhost:{port}")
    print(f"  AI ({ai.provider() or 'none'}) : {('ON, model ' + ai.model_name()) if ai.ai_enabled() else 'demo mode (set GEMINI_API_KEY)'}")
    print(f"  PayPal sandbox: {'ON' if paypal.paypal_enabled() else 'demo mode (set PAYPAL_CLIENT_ID/SECRET)'}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
