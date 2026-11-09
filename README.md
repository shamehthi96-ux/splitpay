# SplitPay

Photograph a restaurant bill, tell the AI who had what in plain English, and everyone gets a PayPal payment request for their exact share (tax and tip included).

Built for the PayPal AI Hackathon.

## How it works

1. **Gemini vision** (Google AI) reads the receipt photo and returns items, tax and tip as structured data.
2. You type something like *"Asha had the pizza, Ravi the burger, we all shared the nachos"*. **Gemini** turns that into item assignments. Tapping chips works too.
3. The split is computed in integer cents: shared items are divided evenly, tax and tip are shared in proportion to each person's subtotal, and the shares always add up to the bill exactly.
4. For each friend, the app creates and sends a **PayPal invoice** (Invoicing v2, sandbox) with their itemised share, as a payment request to their PayPal email. The first person listed is the one who paid, so they don't get a request.

## Run it locally (no installs needed)

Requires Python 3.9+ and nothing else (standard library only).

```bash
git clone <this repo> && cd splitpay
cp env.example .env       # optional: add keys, see below
python3 server.py
# open http://localhost:8000
```

## Deploy (e.g. Render, from a phone)

Create a **Web Service** from this repo with runtime **Python**, no build command, and start command `python3 server.py`. Add the environment variables below in the service settings. The server reads the `PORT` variable the host provides.

## Demo mode vs live mode

With no keys the whole flow still works end to end: a built-in demo receipt is used, assignment uses a keyword fallback, and payment requests are simulated (nothing is sent). The header badges show which parts are live.

| Variable | Where to get it |
|---|---|
| `GEMINI_API_KEY` (free) | https://aistudio.google.com/apikey |
| `GEMINI_MODEL` (optional) | defaults to `gemini-flash-latest` |
| `GEMINI_FALLBACK_MODELS` (optional) | comma-separated models tried in order when the main one is busy (429/5xx) |
| `ANTHROPIC_API_KEY` (optional) | Use Claude instead of Gemini; only read if `GEMINI_API_KEY` is empty |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | https://developer.paypal.com → Apps & Credentials → **Sandbox** |

Use sandbox *personal* account emails as friends' addresses to see the invoices land in the sandbox inbox (sandbox.paypal.com).

## Tests

```bash
python3 -m unittest discover -s . -v
```

- `test_splitlogic.py`: rounding, shared items, proportional tax/tip.
- `test_ai_flow.py`: Gemini request/response handling against a local fake Gemini endpoint (checks our code, not Google's live service).
- `test_paypal_flow.py`: the token → create invoice → send flow against a local fake of the PayPal endpoints. It checks this app's request flow, not PayPal's live schema; use real sandbox credentials for that.

## Files

- `server.py`: tiny HTTP server and API routes
- `ai.py`: AI calls, Gemini by default or Claude (receipt vision, text-to-assignments)
- `paypal.py`: PayPal OAuth + Invoicing
- `splitlogic.py`: bill-splitting maths
- `index.html`: mobile-first UI
- `env.example`: copy to `.env` and fill in (never commit `.env`)

## Limitations

- **India:** PayPal does not let India-based accounts send invoices to customers inside India (sandbox accounts created with country India behave the same). Create the sandbox business account and the recipient accounts with a country such as the United States.
- Sandbox only by default; switch `PAYPAL_BASE_URL` to the live API at your own risk.
- Receipt reading is only as good as the photo, and extracted items/prices can't be edited in the UI yet. Check them against the bill before sending requests.
- Invoices need each friend's PayPal email.

## License

MIT
