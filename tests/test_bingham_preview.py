import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from idaho_permits.collectors.bingham_preview import (
    read_fixture, parse_layout, preview, tracker_preview, HEADERS,
)

FIXTURE = Path(__file__).parent / "fixtures" / "bingham_county_2026-09.csv"
URL = "https://www.binghamid.gov/media/Departments/PlanningandDevelopment/Building%20Permit%20Activity%20Reports/2026%20Reports/September%20BP%20Y2026.pdf"


class BinghamPreviewTests(unittest.TestCase):
    def setUp(self):
        self.rows = read_fixture(FIXTURE)

    def run_preview(self, rows=None):
        return preview(self.rows if rows is None else rows, URL, "2026-09", 43)

    def test_report_counts(self):
        result = self.run_preview()
        self.assertEqual(result["row_count"], 43)
        self.assertEqual(result["identity_count"], 41)
        self.assertEqual(result["latest_issued_date"], "2026-09-29")
        self.assertEqual(result["publication"], "disabled")
        self.assertEqual(sum(Decimal(r["valuation"]) for r in self.rows),
                         Decimal("5735358.45"))

    def test_shared_record_numbers_preserved(self):
        groups = self.run_preview()["groups"]
        for number in ("MFHP-26-10", "BPA-26-74"):
            g = groups[number]
            self.assertEqual(len(g["observations"]), 2)
            self.assertEqual(g["review_status"], "multiple_titles_review")
            with self.assertRaises(ValueError):
                tracker_preview(g)

    def test_tracker_no_owner_as_builder(self):
        groups = self.run_preview()["groups"]
        permits = [tracker_preview(g) for g in groups.values()
                   if g["review_status"] == "single_observation"]
        self.assertEqual(len(permits), 39)
        self.assertEqual(len({p.key for p in permits}), 39)
        self.assertTrue(all(p.contractor is None and p.owner is None
                            and not p.qualifies and p.score == 0 for p in permits))
        self.assertTrue(all(p.jurisdiction == "Bingham County" for p in permits))

    def test_duplicate_row(self):
        bad = [*self.rows[:-1], self.rows[0]]
        with self.assertRaises(ValueError):
            self.run_preview(bad)

    def test_truncation(self):
        with self.assertRaises(ValueError):
            self.run_preview(self.rows[:-1])

    def test_invalid_issue_month(self):
        bad = [{**self.rows[0], "issued_date": "2026-10-01"}, *self.rows[1:]]
        with self.assertRaises(ValueError):
            self.run_preview(bad)

    def test_unapproved_source(self):
        with self.assertRaises(ValueError):
            preview(self.rows, "https://example.com/report.pdf", "2026-09", 43)

    def test_conflicting_same_id_is_not_overwritten(self):
        bad = [dict(r) for r in self.rows]
        next(r for r in bad if r["record_number"] == "MFHP-26-10")["address"] = "changed"
        g = self.run_preview(bad)["groups"]["MFHP-26-10"]
        self.assertEqual(g["review_status"], "conflicting_identity_review")
        self.assertEqual(len(g["observations"]), 2)

    def test_layout_prototype(self):
        widths = [16, 80, 20, 16, 45, 60, 15]
        def line(values):
            return "".join(v.ljust(w) for v,w in zip(values,widths))
        reconstructed = [line(HEADERS)]
        for r in self.rows:
            d = date.fromisoformat(r["issued_date"])
            reconstructed.append(line([r["record_number"], r["title"], "Permit/License",
                f"{d.month}/{d.day}/{d.year}", "REDACTED OWNER", r["address"], r["valuation"]]))
        self.assertEqual(parse_layout("\n".join(reconstructed)), self.rows)

    def test_layout_requires_explicit_issuance(self):
        with self.assertRaises(ValueError):
            parse_layout("Record # Title Type Date Received Owner Name Full Address Value")
