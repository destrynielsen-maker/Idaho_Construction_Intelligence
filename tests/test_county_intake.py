import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from idaho_permits.county_intake import read_batch, merge_preview, tracker_preview

BASE = Path(__file__).parent / "fixtures" / "twin_falls_county_2026-10.csv"


class TestCountyIntake(unittest.TestCase):
    def setUp(self):
        self.rows = read_batch(BASE, 19)

    def test_source_reconciliation(self):
        self.assertEqual(len(self.rows), 19)
        self.assertEqual(sum(r["permit_type"] == "Single Family Residence" for r in self.rows.values()), 5)
        self.assertEqual(max(r["issued_date"] for r in self.rows.values()), "2026-10-30")
        self.assertEqual(sum(Decimal(r["valuation"] or "0") for r in self.rows.values()), Decimal("2420828.01"))

    def test_replay(self):
        result = merge_preview(self.rows, self.rows)
        self.assertEqual(result["preview_count"], 19)
        self.assertEqual(len(result["matched"]), 19)

    def test_partial(self):
        result = merge_preview(self.rows, dict(list(self.rows.items())[:2]))
        self.assertEqual(result["preview_count"], 19)
        self.assertEqual(len(result["missing_from_batch_retained"]), 17)

    def test_conflict(self):
        key = next(iter(self.rows))
        changed = {key: {**self.rows[key], "contractor": "DIFFERENT"}}
        result = merge_preview(self.rows, changed)
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["records"][key], self.rows[key])

    def test_first_seen(self):
        key = next(iter(self.rows))
        old = {**self.rows[key], "first_seen_at": "2026-11-01"}
        result = merge_preview({key: old}, {key: self.rows[key]})
        self.assertEqual(result["records"][key]["first_seen_at"], "2026-11-01")

    def test_no_owner_substitution(self):
        self.assertEqual(sum(not r["contractor"] for r in self.rows.values()), 4)
        self.assertTrue(all(tracker_preview(r).owner is None for r in self.rows.values()))

    def test_tracker_shape_review_only(self):
        records = [tracker_preview(r) for r in self.rows.values()]
        self.assertEqual(len({p.key for p in records}), 19)
        self.assertTrue(all(p.jurisdiction == "Twin Falls County" and p.stage == "PERMITTED" for p in records))
        self.assertTrue(all(not p.qualifies and p.score == 0 and p.raw["publication_status"] == "review_only" for p in records))

    def test_invalid_count(self):
        with self.assertRaises(ValueError):
            read_batch(BASE, 20)

    def altered(self, edit):
        with BASE.open() as f:
            lines = list(csv.reader(f))
        edit(lines)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            with path.open("w", newline="") as f:
                csv.writer(f).writerows(lines)
            with self.assertRaises(ValueError):
                read_batch(path, len(lines) - 1)

    def test_duplicate(self):
        self.altered(lambda a: a.append(a[1]))

    def test_bad_month(self):
        self.altered(lambda a: a[1].__setitem__(2, "2026-09-30"))

    def test_untrusted_source(self):
        self.altered(lambda a: a[1].__setitem__(8, "https://example.com/report.pdf"))

    def test_missing_issue(self):
        self.altered(lambda a: a[1].__setitem__(2, ""))

    def test_issuer_isolation(self):
        self.altered(lambda a: a[1].__setitem__(0, "caldwell_city_id"))
