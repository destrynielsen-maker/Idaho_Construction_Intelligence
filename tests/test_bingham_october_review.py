import unittest
from decimal import Decimal
from pathlib import Path
from idaho_permits.collectors.bingham_preview import read_fixture, preview, tracker_preview

ROOT = Path(__file__).parent / "fixtures"
PREFIX = "https://www.binghamid.gov/media/Departments/PlanningandDevelopment/Building%20Permit%20Activity%20Reports/2026%20Reports/"

class BinghamOctoberReviewTests(unittest.TestCase):
    def test_two_period_reconciliation(self):
        sep = read_fixture(ROOT / "bingham_county_2026-09.csv")
        oct_rows = read_fixture(ROOT / "bingham_county_2026-10.csv")
        a = preview(sep, PREFIX + "September%20BP%20Y2026.pdf", "2026-09", 43)
        b = preview(oct_rows, PREFIX + "October%20BP%20Y2026.pdf", "2026-10", 34)
        self.assertEqual(b["identity_count"], 32)
        self.assertEqual(b["latest_issued_date"], "2026-10-30")
        self.assertEqual(sum(Decimal(r["valuation"]) for r in oct_rows), Decimal("3447992"))
        self.assertFalse(set(a["groups"]) & set(b["groups"]))
        self.assertEqual(len(set(a["groups"]) | set(b["groups"])), 73)
        self.assertEqual(sum(len(g["observations"]) for g in b["groups"].values()), 34)
        for number in ("BPA-26-88", "BPA-26-86"):
            group = b["groups"][number]
            self.assertEqual(group["review_status"], "multiple_titles_review")
            self.assertEqual(len(group["observations"]), 2)
            with self.assertRaises(ValueError):
                tracker_preview(group)
        self.assertEqual(b["publication"], "disabled")
        for group in b["groups"].values():
            if group["review_status"] == "single_observation":
                permit = tracker_preview(group)
                self.assertIsNone(permit.contractor)
                self.assertIsNone(permit.owner)
                self.assertFalse(permit.qualifies)
        self.assertEqual(b, preview(oct_rows, PREFIX + "October%20BP%20Y2026.pdf", "2026-10", 34))

    def test_partial_report_fails_closed(self):
        rows = read_fixture(ROOT / "bingham_county_2026-10.csv")
        with self.assertRaises(ValueError):
            preview(rows[:-1], PREFIX + "October%20BP%20Y2026.pdf", "2026-10", 34)
