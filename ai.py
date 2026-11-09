"""AI integration (Gemini by default, Claude optional): read a receipt photo, and turn plain
English into item assignments. Set GEMINI_API_KEY (free) or ANTHROPIC_API_KEY."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
# "gemini-flash-latest" is Google's alias for the current Flash model; override with GEMINI_MODEL.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_BASE = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

# Used when no AI key is set, so judges can still click through the whole flow.
DEMO_RECEIPT = {
    "merchant": "Demo Bistro",
    "currency": "USD",
    "items": [
        {"id": "1", "name": "Margherita Pizza", "price": 14.00, "qty": 1},
        {"id": "2", "name": "Chicken Burger", "price": 12.50, "qty": 1},
        {"id": "3", "name": "Loaded Nachos (share)", "price": 9.00, "qty": 1},
        {"id": "4", "name": "Craft Lemonade", "price": 8.00, "qty": 2},
        {"id": "5", "name": "Tiramisu", "price": 7.50, "qty": 1},
    ],
    "tax": 3.80,
    "tip": 8.00,
    "demo": True,
}


def provider() -> str:
    """Which AI backend is active: 'gemini', 'claude' or '' (demo mode)."""
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    return ""


def ai_enabled() -> bool:
    return bool(provider())


def model_name() -> str:
    return {"gemini": GEMINI_MODEL, "claude": CLAUDE_MODEL}.get(provider(), "demo")


class ApiError(RuntimeError):
    def __init__(self, label: str, code: int, text: str):
        super().__init__(f"{label} API error {code}: {text[:300]}")
        self.code, self.text = code, text


RETRY_DELAY = 2.0  # seconds, multiplied by attempt number (tests set 0)


def _post_json(url: str, headers: dict, body: dict, label: str, attempts: int = 3) -> dict:
    """POST JSON; retry briefly on busy/overloaded responses (429/5xx) and network blips."""
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            err = ApiError(label, e.code, e.read().decode())
            if e.code in (429, 500, 502, 503, 504) and attempt < attempts:
                time.sleep(RETRY_DELAY * attempt)
                continue
            raise err from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < attempts:
                time.sleep(RETRY_DELAY * attempt)
                continue
            raise RuntimeError(f"{label} request failed: {e}") from None


def _ask(prompt: str, image_b64: str | None = None, media_type: str = "image/jpeg", max_tokens: int = 1500) -> str:
    """Send a prompt (optionally with an image) to the active model and return its text."""
    if provider() == "gemini":
        parts = []
        if image_b64:
            parts.append({"inline_data": {"mime_type": media_type, "data": image_b64}})
        parts.append({"text": prompt})
        url = f"{GEMINI_BASE}/models/{GEMINI_MODEL}:generateContent"
        headers = {"content-type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]}
        cfg = {"responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}
        try:  # thinking off = much faster reads of simple receipts
            data = _post_json(url, headers, {"contents": [{"parts": parts}], "generationConfig": cfg}, "Gemini")
        except ApiError as e:
            if e.code != 400 or "thinking" not in e.text.lower():
                raise
            cfg.pop("thinkingConfig")  # this model doesn't allow it; retry plainly
            data = _post_json(url, headers, {"contents": [{"parts": parts}], "generationConfig": cfg}, "Gemini")
        try:
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError):
            raise RuntimeError(f"Gemini returned no answer: {json.dumps(data)[:300]}") from None

    content = []
    if image_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}})
    content.append({"type": "text", "text": prompt})
    data = _post_json(
        CLAUDE_URL,
        {
            "content-type": "application/json",
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
        },
        {"model": CLAUDE_MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]},
        "Claude",
    )
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _extract_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ValueError("Model did not return JSON")
    return json.loads(text[start:])


RECEIPT_PROMPT = """You are reading a photo of a restaurant or shop receipt (any country, any currency).
Return ONLY a JSON object, no commentary:
{"merchant": string, "currency": ISO code like "USD" or "INR",
 "items": [{"name": string, "price": number (total for that line, not per unit), "qty": integer}],
 "tax": number (sum of all taxes/GST/service charges shown, 0 if none),
 "tip": number (0 if none)}
Do not include the grand total as an item. Use plain numbers without currency symbols."""


def parse_receipt(image_b64: str, media_type: str = "image/jpeg") -> dict:
    if not ai_enabled():
        return dict(DEMO_RECEIPT)
    text = _ask(RECEIPT_PROMPT, image_b64=image_b64, media_type=media_type)
    data = _extract_json(text)
    items = []
    for i, it in enumerate(data.get("items", []), 1):
        items.append(
            {
                "id": str(i),
                "name": str(it.get("name", f"Item {i}")),
                "price": float(it.get("price", 0)),
                "qty": int(it.get("qty", 1) or 1),
            }
        )
    return {
        "merchant": data.get("merchant", ""),
        "currency": data.get("currency", "USD"),
        "items": items,
        "tax": float(data.get("tax", 0) or 0),
        "tip": float(data.get("tip", 0) or 0),
        "demo": False,
    }


ASSIGN_PROMPT = """Assign receipt items to people based on what they said.
Items: {items}
People: {people}
Description: "{text}"

Rules: an item can have several people (they share it equally). "I"/"me" means the person named {me}.
Words like "everyone", "we all shared" mean all people. If an item is not mentioned, leave its list empty.
Return ONLY JSON mapping item id to a list of people names, e.g. {{"1": ["Asha"], "3": ["Asha", "Ravi"]}}.
Use exactly the names provided."""


def _demo_assign(text: str, items, people, me):
    """Keyword fallback so the demo works without an API key."""
    out = {}
    low = text.lower()
    clauses = re.split(r"[.;\n]|,(?!\s*and)", low)
    for it in items:
        name = re.sub(r"\(.*?\)", " ", it["name"].lower())
        words = [w for w in re.findall(r"[a-z]+", name) if len(w) > 3]
        for c in clauses:
            if any(w in c for w in words):
                names = [p for p in people if p.lower() in c]
                if re.search(r"\b(i|me|my)\b", c) and me in people and me not in names:
                    names.append(me)
                if re.search(r"everyone|all of us|we all", c):
                    names = list(people)
                if names:
                    out[it["id"]] = names
    return out


def assign_from_text(text: str, items, people, me: str) -> dict:
    if not ai_enabled():
        return _demo_assign(text, items, people, me)
    compact = [{"id": i["id"], "name": i["name"], "price": i["price"]} for i in items]
    out = _ask(ASSIGN_PROMPT.format(items=json.dumps(compact), people=json.dumps(people), text=text, me=me), max_tokens=800)
    raw = _extract_json(out)
    valid = set(people)
    return {str(k): [p for p in v if p in valid] for k, v in raw.items() if isinstance(v, list)}
