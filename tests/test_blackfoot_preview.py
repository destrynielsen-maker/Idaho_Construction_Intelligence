from datetime import date
import unittest

from idaho_permits.blackfoot_preview import INDEX, discover, parse_rows


PERIOD = date(2026, 10, 1)
TODAY = date(2026, 11, 26)
HEADER_PREFIX = "Record # Record Type Applicant Name Address"
OLD_HEADER = HEADER_PREFIX + " Permit Issued Description Sq Ft"
NEW_HEADER = "Permit Issued " + HEADER_PREFIX + " Description Square Feet Date"
URL = INDEX.rsplit("/", 2)[0] + "/DocumentCenter/View/999/Building-Permit-Report-October-2026"


def row(number="RES-26-1", kind="Residential Building Permit", desc="stick-built house with attached garage", new=True, issued="10/6/2026"):
    identity = [number, kind, "Fictional Applicant Name", "99 Fictional Road"]
    return identity + ([desc, "1,320", issued] if new else [issued, desc, "1,320"])


class BlackfootPreviewTest(unittest.TestCase):
    def parse(self, rows, header=NEW_HEADER):
        return parse_rows(header, rows, PERIOD, TODAY, URL, 1)

    def test_both_verified_layouts_and_no_sensitive_projection(self):
        for hdr, new in ((OLD_HEADER, False), (NEW_HEADER, True)):
            with self.subTest(header=hdr):
                [out] = self.parse([row(new=new)], hdr)
                self.assertEqual(out["issued_date"], "2026-10-06")
                self.assertEqual(out["candidate"]["reported_square_feet"], 1320)
                self.assertFalse(out["candidate"]["qualifies"])
                self.assertIsNone(out["candidate"]["contractor"])
                self.assertNotIn("Fictional", str(out))

    def test_scope_exclusions_and_unit_ambiguity(self):
        inputs = [
            row("MFG-26-1", "Manufactured/Modular/Mobile Home Permit", "setting a manufactured home"),
            row("COMM-26-2", "Commercial Building Permit", "public works facility"),
            row("RES-26-3", desc="addition to existing stick-built house"),
            row("RES-26-4", desc="steel accessory structure"),
            row("RES-26-5", desc="2-bedroom twin home, garage per unit"),
            row("RES-26-6", desc="detached garage for existing home"),
        ]
        output = self.parse(inputs)
        self.assertEqual(sum(bool(x["candidate"]) for x in output), 1)
        twin = output[4]["candidate"]
        self.assertEqual(twin["reported_type"], "twin_home_configuration_unverified")
        self.assertIsNone(twin["units"])
        self.assertFalse(twin["qualifies"])

    def test_rejects_unknown_layout_wrong_dates_and_wrong_source_labels(self):
        with self.assertRaisesRegex(ValueError, "mixed incompatible"):
            self.parse([row(), row(new=False)])
        with self.assertRaisesRegex(ValueError, "outside report month"):
            self.parse([row(issued="9/6/2026")])
        with self.assertRaisesRegex(ValueError, "outside report month"):
            parse_rows(NEW_HEADER, [row(issued="10/31/2026")], PERIOD, date(2026,10,12), URL, 1)
        with self.assertRaisesRegex(ValueError, "headers"):
            self.parse([row()], "different report")
        with self.assertRaisesRegex(ValueError, "disagrees"):
            discover(f'<a href="{URL}">Building Permit Report September 2026</a>', TODAY)

    def test_discovery_allows_unique_city_report_only(self):
        html = f'<a href="{URL}">Building Permit Report October 2026</a>'
        html += '<a href="https://example.org/DocumentCenter/View/2/Building-Permit-Report-November-2026">Building Permit Report November 2026</a>'
        self.assertEqual(discover(html, TODAY), [(PERIOD, URL)])
