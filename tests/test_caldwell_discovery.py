import unittest
from idaho_permits.classify import classify_permit
from idaho_permits.collectors.caldwell import records_from_page

HTML = '''
<h4>July 2026</h4>
<table>
<tr><th>Development</th><th>Agency</th><th>Checklist</th><th>Application</th></tr>
<tr><td>Highline Industrial Park Subdivision</td><td>City of Caldwell</td><td><a href="/highline-check.pdf">Checklist</a></td><td><a href="/highline-app.pdf">Application</a></td></tr>
<tr><td>North Celeste Subdivision</td><td>City of Caldwell</td><td><a href="/celeste-check.pdf">Checklist</a></td><td><a href="/celeste-app.pdf">Application</a></td></tr>
<tr><td>Summerlin Neighborhood</td><td>City of Meridian</td><td></td><td></td></tr>
</table>
<h4>June 2026</h4>
<table><tr><td>Isbell Townhomes</td><td>City of Caldwell</td><td><a href="/isbell.pdf">Checklist</a></td><td></td></tr></table>
<h4>May 2026</h4>
<table><tr><td>KCID Commercial Subdivision</td><td>City of Caldwell</td><td></td><td><a href="/kcid.pdf">Application</a></td></tr></table>
'''

class CaldwellCompassTests(unittest.TestCase):
    def test_keeps_only_caldwell_rows_with_month_and_links(self):
        rows = records_from_page(HTML, 'https://compassidaho.org/development-review-checklists-2026/', 2026)
        self.assertEqual(len(rows), 4)
        by_name = {p.project_name: p for p in rows}
        highline = by_name['Highline Industrial Park Subdivision']
        self.assertEqual(highline.issued_date, '2026-07-01')
        self.assertEqual(highline.stage, 'PLANNING')
        self.assertEqual(highline.city, 'Caldwell')
        self.assertEqual(highline.source_url, 'https://compassidaho.org/highline-app.pdf')
        self.assertTrue(highline.permit_number.startswith('COMPASS-202607-'))

    def test_explicit_industrial_commercial_and_townhome_projects_qualify(self):
        rows = records_from_page(HTML, 'https://compassidaho.org/', 2026)
        by_name = {p.project_name: classify_permit(p) for p in rows}
        self.assertTrue(by_name['Highline Industrial Park Subdivision'].qualifies)
        self.assertEqual(by_name['Highline Industrial Park Subdivision'].classification, 'COMMERCIAL')
        self.assertTrue(by_name['KCID Commercial Subdivision'].qualifies)
        self.assertTrue(by_name['Isbell Townhomes'].qualifies)
        self.assertEqual(by_name['Isbell Townhomes'].classification, 'MULTIFAMILY')
        self.assertFalse(by_name['North Celeste Subdivision'].qualifies)

if __name__ == '__main__':
    unittest.main()
