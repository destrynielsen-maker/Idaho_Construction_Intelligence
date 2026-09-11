import unittest
from datetime import date

from idaho_permits.collectors.report_pages import MeridianDirectCollector, parse_meridian


class MeridianReportTests(unittest.TestCase):
    def test_block_parser_does_not_borrow_previous_permit_number(self):
        text = """
COMMERCIAL
Miscellaneous
Permit #
C-MISC-2026-0004
Issued:
09/04/2026
Valuation:
$26,919.52
Address:
3080 N CAJUN LN
Project Description:
CentrePoint Apartments Carports Building D - apartment project accessory carports.
TOTAL VALUE:
$26,919.52
1
PERMITS
COMMERCIAL
New
Permit #
C-MULTI-2026-0008
Issued:
09/04/2026
Valuation:
$3,987,567.82
Address:
3080 N CAJUN LN
Contractor:
Headwaters Construction Company
Project Description:
Centrepoint Apartments Building D - To construct a new 27,079 sq.ft. three-story 22-unit multi-family building. - # of Units:
22
Permit #
C-NEW-2026-0027
Issued:
09/03/2026
Valuation:
$2,000,000.00
Address:
233 S TALLAC LN
Contractor:
PERRYMAN CONSTRUCTION MANAGEMENT INC
Project Description:
OUTERBANKS CLUBHOUSE - A new ground up clubhouse for the multifamily apartment complex.
"""
        permits = parse_meridian(text, 'Meridian', 'https://example.test/report.pdf')
        by_number = {p.permit_number: p for p in permits}
        self.assertEqual(set(by_number), {'C-MULTI-2026-0008', 'C-NEW-2026-0027'})
        multi = by_number['C-MULTI-2026-0008']
        self.assertEqual(multi.issued_date, '2026-09-04')
        self.assertEqual(multi.units, 22)
        self.assertEqual(multi.valuation, 3987567.82)
        self.assertEqual(multi.address, '3080 N CAJUN LN')
        self.assertEqual(multi.contractor, 'Headwaters Construction Company')

    def test_project_word_residential_does_not_change_section(self):
        text = """
COMMERCIAL
New
Permit #
C-MULTI-2026-0008
Issued:
09/04/2026
Valuation:
$3,987,567.82
Address:
3080 N CAJUN LN
Project Description:
Centrepoint Apartments Building D - THE PROJECT IS A
RESIDENTIAL
APARTMENT UNITS IN FIVE UNIQUE BUILDINGS. K.A. - To construct a new multi-family building. - # of Units:
22
Permit #
C-NEW-2026-0027
Issued:
09/03/2026
Valuation:
$2,000,000.00
Address:
233 S TALLAC LN
Project Description:
OUTERBANKS CLUBHOUSE - A new ground up clubhouse.
"""
        permits = parse_meridian(text, 'Meridian', 'https://example.test/report.pdf')
        self.assertEqual({p.permit_number for p in permits}, {'C-MULTI-2026-0008', 'C-NEW-2026-0027'})

    def test_report_end_uses_period_end(self):
        collector = MeridianDirectCollector()
        self.assertEqual(collector._report_end('2026-08-31 through 2026-09-06'), date(2026, 9, 6))
        self.assertIsNone(collector._report_end('Week 1'))


if __name__ == '__main__':
    unittest.main()
