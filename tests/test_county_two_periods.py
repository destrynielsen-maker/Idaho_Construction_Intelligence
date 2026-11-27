import unittest
from decimal import Decimal
from pathlib import Path
from idaho_permits.county_intake import read_batch, merge_preview, tracker_preview

FIXTURES = Path(__file__).parent / "fixtures"

class TwoPeriodCountyTests(unittest.TestCase):
    def test_september_official_totals(self):
        rows = read_batch(FIXTURES / "twin_falls_county_2026-09.csv", 30)
        self.assertEqual(sum(Decimal(r["valuation"] or "0") for r in rows.values()), Decimal("10333504.06"))
        self.assertEqual(max(r["issued_date"] for r in rows.values()), "2026-09-30")
        self.assertEqual(sum(not r["contractor"] for r in rows.values()), 5)
        self.assertEqual(sum(r["permit_type"] == "Single Family Residence" for r in rows.values()), 15)
        self.assertEqual(sum(r["permit_type"] == "Single Family Residence" and r["work_type"] == "New" for r in rows.values()), 13)
        # County subtype alone is not evidence of a new residence: 0550 is a detached shop.
        a = rows["twin_falls_county_id:B2026-0549:issued"]
        b = rows["twin_falls_county_id:B2026-0550:issued"]
        self.assertEqual(a["project_address"], b["project_address"])
        self.assertNotEqual(tracker_preview(a).key, tracker_preview(b).key)
        self.assertFalse(tracker_preview(b).qualifies)

    def test_cross_period_history_repeat_and_partial(self):
        sep = read_batch(FIXTURES / "twin_falls_county_2026-09.csv", 30)
        oct = read_batch(FIXTURES / "twin_falls_county_2026-10.csv", 19)
        self.assertFalse(set(sep) & set(oct))
        first = {k: {**r, "first_seen_at": "2026-10-01"} for k, r in sep.items()}
        combined = merge_preview(first, oct)
        self.assertEqual(combined["preview_count"], 49)
        self.assertEqual(len(combined["added"]), 19)
        self.assertEqual(len(combined["missing_from_batch_retained"]), 30)
        self.assertEqual(combined["conflicts"], [])
        for k in first:
            self.assertEqual(combined["records"][k], first[k])
        replay = merge_preview(combined["records"], sep)
        self.assertEqual(len(replay["matched"]), 30)
        self.assertEqual(replay["preview_count"], 49)
        self.assertEqual(replay["records"], combined["records"])
        partial = merge_preview(replay["records"], dict(list(oct.items())[:1]))
        self.assertEqual(partial["records"], combined["records"])
        self.assertEqual(len({tracker_preview(r).key for r in partial["records"].values()}), 49)
