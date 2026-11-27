import csv
import unittest
from collections import Counter
from datetime import date
from pathlib import Path

from idaho_permits.twin_falls_city_preview import (
    SOURCE, TYPES, read_review_csv, validate_rows, merge_review, parse_layout_pages,
)

FIXTURE = Path(__file__).parent / "fixtures" / "twin_falls_city_2026-10_review.csv"
START, END = date(2026, 10, 1), date(2026, 11, 1)
COUNTS = dict(zip(TYPES, [2, 1, 7, 2, 23, 1, 2, 3]))

class TestTwinFallsCityPreview(unittest.TestCase):
    def setUp(self):
        self.data = read_review_csv(FIXTURE, START, END, COUNTS)
        with FIXTURE.open() as f:
            self.rows = list(csv.DictReader(f))

    def test_report_reconciliation(self):
        self.assertEqual(len(self.data), 41)
        self.assertEqual(Counter(r["permit_type"] for r in self.data.values()), COUNTS)
        self.assertEqual(max(r["issued_date"] for r in self.data.values()), "2026-10-30")
        self.assertEqual({r["source_page"] for r in self.data.values()}, set(map(str,range(1,9))))

    def test_builder_roles(self):
        single = Counter(r["contractor"] for r in self.data.values() if r["permit_type"] == TYPES[4])
        self.assertEqual(single["WOLVERTON HOMES LLC"], 11)
        self.assertEqual(single["Hayden Homes Idaho LLC"], 4)
        self.assertEqual(single["Zernickow Family Investments, Inc"], 2)
        self.assertEqual(sum(r["contractor"] is None for r in self.data.values()), 2)
        self.assertTrue(all(r["owner"] is None for r in self.data.values()))

    def test_parent_and_duplexes_held_for_review(self):
        self.assertEqual(sum(r["relationship_review_required"] for r in self.data.values()), 3)
        self.assertEqual(sum(r["parent_marker"] == "1" for r in self.data.values()), 1)
        self.assertTrue(all(r["publication"] == "review_only" for r in self.data.values()))

    def test_partial_replay_and_conflict(self):
        key = next(iter(self.data))
        old = {**self.data[key], "first_seen_at": "2026-11-01"}
        existing = {**self.data, key:old}
        result, conflicts = merge_review(existing, {key:self.data[key]})
        self.assertEqual(result, existing)
        self.assertEqual(conflicts, [])
        result, conflicts = merge_review(existing, {key:{**self.data[key], "contractor_field":"CHANGED"}})
        self.assertEqual(result, existing)
        self.assertEqual(conflicts,[key])

    def test_missing_and_duplicate_rows_fail(self):
        for bad in [self.rows[:-1], self.rows + self.rows[:1]]:
            with self.assertRaises(ValueError):
                validate_rows(bad, START, END, COUNTS)

    def test_application_date_never_substituted(self):
        bad = [dict(r) for r in self.rows]
        bad[0]["issued_date"] = bad[0]["application_date"]
        with self.assertRaises(ValueError):
            validate_rows(bad, START, END, COUNTS)

    def test_source_scope(self):
        with self.assertRaises(ValueError):
            validate_rows(self.rows, START, END, COUNTS, "https://example.org/Archive/ViewFile/Item/3493")

    def test_layout_prototype_synthetic(self):
        page = "\n".join([
            "Permit List",
            "Permit #: 26-2455   Duplex (2-family dwelling on one lot)   Application Date: 9/1/2026   Issued Date: 10/30/2026",
            "Permit Address: 151 & 149 Ibex Loop      Valuation: $378,582.24    Fees Paid: $14,566.06",
            "Owner: OMITTED          Contractor: Elevated Homes LLC",
            "                        Description of Work: Federation Point Phase 2",
            "                        Parent",
            "Total # of Permits: 3".replace("3","1"),
        ])
        rows, counts = parse_layout_pages([page])
        self.assertEqual(counts, {TYPES[7]:1})
        parsed = validate_rows(rows, START, END, counts)
        self.assertEqual(next(iter(parsed.values()))["parent_marker"], "1")
        self.assertEqual(next(iter(parsed.values()))["contractor"],"Elevated Homes LLC")
        with self.assertRaises(ValueError):
            parse_layout_pages([page.replace("Total # of Permits: 1","Total # of Permits: 2")])

