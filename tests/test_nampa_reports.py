import unittest
from datetime import date

from idaho_permits.classify import classify_permit
from idaho_permits.collectors.nampa import NampaPermitCollector, parse_nampa


class NampaReportTests(unittest.TestCase):
    def test_report_end_uses_weekly_period_end(self):
        collector = NampaPermitCollector()
        self.assertEqual(collector._report_end('08/31/2026 – 09/04/2026'), date(2026, 9, 4))
        self.assertIsNone(collector._report_end('September 2026'))

    def test_parser_keeps_ground_up_and_rejects_addition_in_real_pdf_shape(self):
        text = """
Project Type: Commercial
Occupancy By Group: <undefined>
Tax Account: Urban Renewal Area: No
Permit Number: COM-05510-2026 Situs: 993 S Almond St Nampa, Id 83686
$400,000..............
09/04/2026Issue Date: Project Name: Intermountain West Homes No. 2
1.00Unit:
Scope of Work: New Construction. R4 Residential Care Home. 8 or under individuals
Bryan Wright Contact Intermountain West HomesApplicant, Foreman, Owner 1, Registered Building
Contractor
Tax Account: Urban Renewal Area: Yes
Permit Number: COM-05512-2026 Situs: 1830 Caldwell Blvd Nampa, Id 83651
$450,000..............
09/04/2026Issue Date: Project Name: Texas Roadhouse-Cooler Addition
Unit:
Scope of Work: THE DEMOLITION OF EXISTING LANDSCAPED AREA AND SIDEWALK. THE ADDITION OF NEW WALK-IN COOLERS AT 195 SF.
Steve Holden Hatton Construction CompanyRegistered Building Contractor
Project Type: Residential
Structure Use: Residential: Single-Family
Tax Account: Urban Renewal Area: No
Permit Number: RES-18696-2026 Situs: 4060 S Harvest Creek Way Nampa, Id 83686
$137,949..............
09/03/2026Issue Date: Project Name: NEW SFD LT70 BLK07 Harvest Creek #5
1.00Unit:
Scope of Work: NEW SFD-GARAGE W/COVERED PATIO LT70 BLK07 Harvest Creek #5
Hayden WatsonOwner 1, Registered Building Contractor
"""
        permits = parse_nampa(text, 'Nampa', 'https://example.test/nampa.pdf')
        by_number = {permit.permit_number: permit for permit in permits}
        self.assertEqual(set(by_number), {'COM-05510-2026', 'RES-18696-2026'})
        self.assertEqual(by_number['COM-05510-2026'].valuation, 400000.0)
        self.assertEqual(by_number['COM-05510-2026'].issued_date, '2026-09-04')
        self.assertEqual(by_number['COM-05510-2026'].units, 1)
        self.assertEqual(by_number['RES-18696-2026'].issued_date, '2026-09-03')

        commercial = classify_permit(by_number['COM-05510-2026'])
        residence = classify_permit(by_number['RES-18696-2026'])
        self.assertTrue(commercial.qualifies)
        self.assertEqual(commercial.classification, 'COMMERCIAL')
        self.assertTrue(residence.qualifies)
        self.assertEqual(residence.classification, 'SINGLE_FAMILY')

    def test_townhouse_maps_to_multifamily(self):
        text = """
Project Type: Residential
Structure Use: Residential: Townhouse
Tax Account: Urban Renewal Area: No
Permit Number: RES-18780-2026 Situs: 15587 N Exeter Way Nampa, Id 83651
$125,990..............
09/03/2026Issue Date: Project Name: NEW SF TOWNHOUSE LT23 BLK07 MIDDLEBURY NORTH #2
1.00Unit:
Scope of Work: NEW SF TOWNHOUSE-GARAGE W/COVERED PORCH LT23 BLK07 MIDDLEBURY NORTH #2
Anjelica Cheek Cbh HomesApplicant
"""
        permits = parse_nampa(text, 'Nampa', 'https://example.test/nampa.pdf')
        self.assertEqual(len(permits), 1)
        permit = classify_permit(permits[0])
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, 'MULTIFAMILY')

    def test_interior_new_finishes_do_not_count_as_ground_up(self):
        text = """
Project Type: Commercial
Tax Account: Urban Renewal Area: No
Permit Number: COM-05559-2026 Situs: 5681 E Franklin Rd Nampa, Id 83687
$400,000..............
09/02/2026Issue Date: Project Name: Domino's Pizza Bakery & Store #7976
Unit:
Scope of Work: New interior partitions, casework, fixed furniture, kitchen equipment for retail food bakery and store.
Devon Tripp Perigee Group, LlcRegistered Building Contractor
"""
        self.assertEqual(parse_nampa(text, 'Nampa', 'https://example.test/nampa.pdf'), [])


if __name__ == '__main__':
    unittest.main()
