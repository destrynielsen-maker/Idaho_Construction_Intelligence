import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from requests import HTTPError

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


    def test_associated_company_only_and_same_permit_binding(self):
        text='''Project Type: Residential
Permit Number: RES-18696-2026 Situs: 4060 S Harvest Creek Way
09/03/2026Issue Date: Project Name: NEW SFD
1.00Unit:
Scope of Work: New SFD
First Person Example Homes LlcRegistered Building Contractor
Permit Number: RES-18697-2026 Situs: 4061 S Harvest Creek Way
09/03/2026Issue Date: Project Name: NEW SFD
1.00Unit:
Scope of Work: New SFD
Other PersonRegistered Building Contractor
'''
        layout='''Permit Number:    RES-18696-2026    Situs:     4060 S Harvest Creek Way
Owner 1, Registered Building Contractor      First Person        Example Homes Llc
Permit Number:    RES-18697-2026    Situs:     4061 S Harvest Creek Way
Owner 1, Registered Building Contractor      Other Person
'''
        p=parse_nampa(text,'Nampa','https://example.test/report.pdf',layout=layout)
        self.assertEqual([x.contractor for x in p],['Example Homes Llc',None])
        self.assertNotIn('First Person',str(p[0].raw))
        self.assertEqual(p[0].raw['contractor_role'],'Registered Building Contractor / Associated Company')

    def test_city_linked_pdf_fallback_is_not_labeled_current(self):
        text='''CITY OF NAMPA, Department of Building Safety
Permit Activity Type Report
10/19/2026 to 10/23/2026
Project Type: Residential
Permit Number: RES-18788-2026 Situs: 1 Example Lane
10/22/2026Issue Date: Project Name: NEW SFD
1.00Unit:
Scope of Work: New SFD
'''
        layout='Permit Number:     RES-18788-2026     Situs: 1 Example Lane'
        page=SimpleNamespace(extract_text=lambda **kwargs: layout if kwargs else text)
        url=NampaPermitCollector.direct_report[1]
        result=SimpleNamespace(content=b'%PDF',url=url)
        with patch('idaho_permits.collectors.nampa.discover_links',side_effect=HTTPError('403')),             patch('idaho_permits.collectors.nampa.get',return_value=result),             patch('idaho_permits.collectors.nampa.PdfReader',return_value=SimpleNamespace(pages=[page])):
            collected=NampaPermitCollector().collect()
        self.assertEqual(collected.status,'stale')
        self.assertIn('direct fallback',collected.note)
        self.assertEqual(collected.latest_issued_date,'2026-10-22')
        self.assertEqual(collected.report_period_end,'2026-10-23')
        self.assertTrue(collected.progress_complete)
        row, = collected.progress
        self.assertEqual((row['stage'], row['issue_date'], row['source_url']), ('issued', '2026-10-22', url))
        self.assertIsNone(row['issued_flag'])
        self.assertIsNone(row['received_date'])
        self.assertIsNone(row['source_status'])

if __name__ == '__main__':
    unittest.main()
