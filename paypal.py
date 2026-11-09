"""PayPal Invoicing v2 (sandbox): send each friend a payment request for their share."""

from __future__ import annotations

import base64
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from splitlogic import cents_str

BASE = os.environ.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")


def paypal_enabled() -> bool:
    return bool(os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_CLIENT_SECRET"))


def _request(method, path, body=None, token=None, form=None, basic=None):
    headers = {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["content-type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["content-type"] = "application/json"
    if token:
        headers["authorization"] = f"Bearer {token}"
    if basic:
        headers["authorization"] = "Basic " + base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"PayPal {method} {path} -> {e.code}: {e.read().decode()[:400]}") from None


def get_token() -> str:
    r = _request(
        "POST",
        "/v1/oauth2/token",
        form={"grant_type": "client_credentials"},
        basic=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
    )
    return r["access_token"]


def _invoice_payload(person: dict, share: dict, merchant: str, currency: str, note: str) -> dict:
    items = [
        {
            "name": line["name"][:200],
            "quantity": "1",
            "unit_amount": {"currency_code": currency, "value": cents_str(line["cents"])},
        }
        for line in share["items"]
    ]
    for label, key in (("Tax share", "tax_cents"), ("Tip share", "tip_cents")):
        if share[key] > 0:
            items.append(
                {
                    "name": label,
                    "quantity": "1",
                    "unit_amount": {"currency_code": currency, "value": cents_str(share[key])},
                }
            )
    detail = {
        "currency_code": currency,
        "invoice_date": datetime.date.today().isoformat(),
        "note": note[:400],
        "memo": f"Split bill at {merchant}"[:150] if merchant else "Split bill",
        "payment_term": {"term_type": "DUE_ON_RECEIPT"},
    }
    return {
        "detail": detail,
        "primary_recipients": [
            {"billing_info": {"name": {"given_name": person["name"]}, "email_address": person["email"]}}
        ],
        "items": items,
    }


def send_requests(shares: dict, people: list[dict], merchant: str, currency: str, note: str) -> list[dict]:
    """Create + send one invoice per person. Returns a result row per person."""
    emails = {p["name"]: p.get("email", "").strip() for p in people}
    results = []

    if not paypal_enabled():
        for name, share in shares.items():
            if share["total_cents"] <= 0:
                continue
            results.append(
                {
                    "name": name,
                    "amount": cents_str(share["total_cents"]),
                    "status": "demo",
                    "detail": "No PayPal credentials set - simulated (nothing was sent).",
                }
            )
        return results

    token = get_token()
    for name, share in shares.items():
        if share["total_cents"] <= 0:
            continue
        row = {"name": name, "amount": cents_str(share["total_cents"]), "currency": currency}
        if not emails.get(name):
            row.update(status="skipped", detail="No email address for this person.")
            results.append(row)
            continue
        try:
            created = _request(
                "POST",
                "/v2/invoicing/invoices",
                body=_invoice_payload({"name": name, "email": emails[name]}, share, merchant, currency, note),
                token=token,
            )
            href = created["href"]
            sent = _request(
                "POST",
                href + "/send",
                body={"send_to_recipient": True, "send_to_invoicer": False},
                token=token,
            )
            row.update(
                status="sent",
                invoice_id=href.rsplit("/", 1)[-1],
                link=sent.get("href", ""),
                detail="Invoice sent via PayPal sandbox.",
            )
        except Exception as e:  # keep going so one bad email doesn't block the rest
            row.update(status="error", detail=str(e))
        results.append(row)
    return results
