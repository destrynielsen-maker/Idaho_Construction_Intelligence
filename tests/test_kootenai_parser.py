import unittest

from idaho_permits.collectors.kootenai_county import parse_kootenai


class KootenaiParserTests(unittest.TestCase):
    def test_new_sfr_is_extracted(self):
        text = """
        RESIDENTIAL BUILDING 24054 [TEMP] N Eclipse Road TIMBERED RIDGE HOMES LLC $599,629.48 $8,861.38 $8,861.38
        NEW ONE FAMILY
        DWELLING
        0M0930070300 TIMBERED RIDGE HOMES LLC
        Issued
        RES26-0322
        3/23/2026
        Permit Title: NEW SFR w/ATTACHED GARAGE | Timbered Ridge
        """
        permits = parse_kootenai(text, "https://example.test/report.pdf")
        self.assertEqual(len(permits), 1)
        permit = permits[0]
        self.assertEqual(permit.permit_number, "RES26-0322")
        self.assertEqual(permit.issued_date, "2026-03-23")
        self.assertIn("24054", permit.address)
        self.assertEqual(permit.valuation, 599629.48)
        self.assertIn("TIMBERED RIDGE", permit.contractor)

    def test_remodel_noise_is_skipped(self):
        text = """
        RESIDENTIAL BUILDING 4294 W Pleasant Ln DAVID PETERS $15,980.00 $376.00 $376.00
        BUILDING EXTERIOR
        RES26-0349
        3/23/2026
        Permit Title: TEAR OFF & RE-ROOF | Peters
        """
        self.assertEqual(parse_kootenai(text, "https://example.test/report.pdf"), [])


if __name__ == "__main__":
    unittest.main()
