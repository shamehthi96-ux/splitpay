"""Pure bill-splitting logic. All money is handled in integer cents."""

from __future__ import annotations


def to_cents(value) -> int:
    return int(round(float(value or 0) * 100))


def _distribute(total_cents: int, weights: dict[str, int]) -> dict[str, int]:
    """Split total_cents across keys proportionally to weights (largest remainder)."""
    keys = list(weights)
    if not keys or total_cents == 0:
        return {k: 0 for k in keys}
    wsum = sum(weights.values())
    if wsum == 0:
        base, extra = divmod(total_cents, len(keys))
        return {k: base + (1 if i < extra else 0) for i, k in enumerate(keys)}
    raw = {k: total_cents * weights[k] / wsum for k in keys}
    out = {k: int(raw[k]) for k in keys}
    leftover = total_cents - sum(out.values())
    for k in sorted(keys, key=lambda k: raw[k] - out[k], reverse=True)[:leftover]:
        out[k] += 1
    return out


def split_bill(items, assignments, people, tax=0, tip=0):
    """
    items:       [{"id": str, "name": str, "price": float (line total), "qty": int}]
    assignments: {item_id: [person names]}  (several names = shared equally)
    people:      [person names]
    tax, tip:    amounts in currency units, shared proportionally to each person's subtotal

    Returns {"people": {name: {...}}, "unassigned": [item ids], "total_cents": int}
    """
    sub = {p: 0 for p in people}
    lines = {p: [] for p in people}
    unassigned = []

    for it in items:
        price = to_cents(it["price"])
        owners = [p for p in assignments.get(it["id"], []) if p in sub]
        if not owners:
            unassigned.append(it["id"])
            continue
        shares = _distribute(price, {p: 1 for p in owners})
        for p in owners:
            sub[p] += shares[p]
            label = it["name"] + (f" (1/{len(owners)})" if len(owners) > 1 else "")
            lines[p].append({"name": label, "cents": shares[p]})

    tax_c, tip_c = to_cents(tax), to_cents(tip)
    tax_split = _distribute(tax_c, sub)
    tip_split = _distribute(tip_c, sub)

    result = {}
    for p in people:
        result[p] = {
            "items": lines[p],
            "subtotal_cents": sub[p],
            "tax_cents": tax_split[p],
            "tip_cents": tip_split[p],
            "total_cents": sub[p] + tax_split[p] + tip_split[p],
        }
    return {
        "people": result,
        "unassigned": unassigned,
        "total_cents": sum(r["total_cents"] for r in result.values()),
    }


def cents_str(c: int) -> str:
    return f"{c // 100}.{c % 100:02d}"
