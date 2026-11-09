import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from splitlogic import split_bill  # noqa: E402

ITEMS = [
    {"id": "1", "name": "Pasta", "price": 14.00, "qty": 1},
    {"id": "2", "name": "Burger", "price": 12.00, "qty": 1},
    {"id": "3", "name": "Nachos", "price": 9.00, "qty": 1},
]


class SplitTests(unittest.TestCase):
    def test_totals_match_bill_exactly(self):
        r = split_bill(ITEMS, {"1": ["A"], "2": ["B"], "3": ["A", "B"]}, ["A", "B"], tax=2.80, tip=7.00)
        self.assertEqual(r["total_cents"], 3500 + 280 + 700)
        self.assertEqual(r["unassigned"], [])

    def test_shared_item_with_odd_cents(self):
        items = [{"id": "x", "name": "Pizza", "price": 10.00, "qty": 1}]
        r = split_bill(items, {"x": ["A", "B", "C"]}, ["A", "B", "C"])
        self.assertEqual(sum(p["total_cents"] for p in r["people"].values()), 1000)

    def test_tax_and_tip_proportional(self):
        r = split_bill(ITEMS, {"1": ["A"], "2": ["B"], "3": ["B"]}, ["A", "B"], tax=3.50, tip=0)
        self.assertEqual(r["people"]["A"]["tax_cents"], 140)
        self.assertEqual(r["people"]["B"]["tax_cents"], 210)

    def test_unassigned_reported(self):
        r = split_bill(ITEMS, {"1": ["A"]}, ["A", "B"])
        self.assertEqual(r["unassigned"], ["2", "3"])

    def test_unknown_person_ignored(self):
        r = split_bill(ITEMS, {"1": ["Ghost"]}, ["A"])
        self.assertEqual(r["unassigned"], ["1", "2", "3"])


if __name__ == "__main__":
    unittest.main()
