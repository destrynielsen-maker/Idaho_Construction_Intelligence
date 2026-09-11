import unittest
from datetime import date

from idaho_permits.classify import classify_permit
from idaho_permits.collectors.kootenai_county import KootenaiCountyCollector, parse_kootenai


class KootenaiParserTests(unittest.TestCase):
    def test_new_sfr_layout_row_is_extracted_exactly(self):
        text = """
RES26-1201     RESIDENTIAL BUILDING        28325 [TEMP] N Lewellen          SARIDGE LLC | Sarah Anderson                  $420,699.16             $7,260.01            $7,260.01
9/3/2026       NEW ONE FAMILY              53N03W241900                     BLUE COLLAR CONTRACTING LLC
               Issued                      Permit Title: NEW SFR w/ATTACHED GARAGE PARCEL #2| Saridge
RES26-1218     RESIDENTIAL BUILDING        31233 N Riffle Rd                 JACOB M CROSBY                               $125,373.60             $4,704.15            $4,704.15
9/3/2026       ACCESSORY STRUCTURE          53N03W241901
               Issued                      Permit Title: NEW POLE STRUCTURE w/ LEAN-TO | Crosby
"""
        permits = parse_kootenai(text, "https://example.test/report.pdf")
        self.assertEqual(len(permits), 1)
        permit = permits[0]
        self.assertEqual(permit.permit_number, "RES26-1201")
        self.assertEqual(permit.issued_date, "2026-09-03")
        self.assertEqual(permit.address, "28325 [TEMP] N Lewellen")
        self.assertEqual(permit.valuation, 420699.16)
        self.assertEqual(permit.contractor, "BLUE COLLAR CONTRACTING LLC")
        classified = classify_permit(permit)
        self.assertEqual(classified.classification, "SINGLE_FAMILY")
        self.assertTrue(classified.qualifies)

    def test_cancelled_sfr_and_remodel_noise_are_skipped(self):
        text = """
RES26-1342     RESIDENTIAL BUILDING        23576 N Eclipse Rd [TEMP]         TIMBERED RIDGE HOMES LLC                      $675,843.85             $9,545.68            $9,545.68
9/3/2026       NEW ONE FAMILY              0M0930070340                      TIMBERED RIDGE HOMES LLC
               Cancelled                   Permit Title: NEW SFR w/ATTACHED GARAGE | Timbered Ridge
RES26-1455     RESIDENTIAL BUILDING        3344 W Bean Ave                    SETH M CLARK                                   $24,000.00              $376.00               $376.00
9/1/2026       BUILDING EXTERIOR           0A0000000000
               Issued                      Permit Title: TEAR OFF AND RE-ROOF HOUSE | Clark residence
"""
        self.assertEqual(parse_kootenai(text, "https://example.test/report.pdf"), [])

    def test_commercial_new_building_is_kept_but_utility_work_is_not(self):
        text = """
COM26-0099     COMMERCIAL BUILDING         1000 W Commerce Dr               EXAMPLE OWNER LLC                             $2,500,000.00           $20,000.00           $20,000.00
9/2/2026       NEW COMMERCIAL BUILDING      00A000000001                     EXAMPLE CONSTRUCTION LLC
               Issued                      Permit Title: NEW COMMERCIAL BUILDING | Commerce Center
COM26-0014     COMMERCIAL BUILDING         51337 N Old Highway 95           OLD 95 BUSINESS PARK LLC                       $40,653.60             $2,062.42            $2,062.42
9/2/2026       UTILITY                     00A000000002
               Issued                      Permit Title: NEW BOOSTER STATION + REPLACEMENT OF WATER
"""
        permits = parse_kootenai(text, "https://example.test/report.pdf")
        self.assertEqual([p.permit_number for p in permits], ["COM26-0099"])
        classified = classify_permit(permits[0])
        self.assertEqual(classified.classification, "COMMERCIAL")
        self.assertTrue(classified.qualifies)

    def test_report_name_is_week_start_not_data_end(self):
        collector = KootenaiCountyCollector()
        self.assertEqual(
            collector._report_start("WEEKLY BUILDING PERMIT REPORT AUGUST 30, 2026"),
            date(2026, 8, 30),
        )
        self.assertIsNone(collector._report_start("Weekly Building Permit Report"))


if __name__ == "__main__":
    unittest.main()
