import unittest
from idaho_permits.collectors.caldwell import (
    build_blank_permit_search,
    summarize_result_page,
    summarize_search_page,
)

HTML = '''
<html><head><title>Citizenserve Online Portal</title></head><body>
<form method="post" action="/Portal/PortalController">
<input type="hidden" name="Action" value="DisplayCasesNPagging" />
<input type="hidden" name="uniqueID" value="abc123" />
<input type="hidden" name="StartIndex" value="0" />
<input type="hidden" name="EndIndex" value="30" />
<select name="filetype"><option value="-999">All</option><option value="Permit">Permitting</option></select>
<input type="text" name="address" />
<input type="text" name="parcelNumber" />
</form>
<table><tr><th>Permit #</th><th>Address</th><th>Status</th></tr><tr><td>BP-1</td><td>1 Main</td><td>Issued</td></tr></table>
<a href="/Portal/PortalController?Action=showSearchPage&type=Permit">Search for permit</a>
</body></html>
'''

RESULT_HTML = '''
<html><head><title>Search Results</title></head><body>
<table>
<tr><th>Permit #</th><th>Address</th><th>Status</th></tr>
<tr><td><a href="/Portal/PortalController?Action=showPermit&workorderID=42">BP-1</a></td><td>1 Main</td><td>Issued</td></tr>
</table>
</body></html>
'''

class CaldwellDiscoveryTests(unittest.TestCase):
    def test_captures_form_controls_tables_and_links(self):
        summary = summarize_search_page(HTML, 'https://www2.citizenserve.com/example')
        self.assertEqual(summary['title'], 'Citizenserve Online Portal')
        self.assertEqual(summary['forms'][0]['method'], 'post')
        names = [x['name'] for x in summary['forms'][0]['controls']]
        self.assertIn('Action', names)
        self.assertIn('filetype', names)
        self.assertIn('address', names)
        self.assertEqual(summary['tables'][0]['headers'], ['Permit #', 'Address', 'Status'])
        self.assertIn('permit', summary['links'][0]['label'].lower())

    def test_builds_blank_permit_search_from_live_form_shape(self):
        action, payload = build_blank_permit_search(HTML, 'https://www2.citizenserve.com/example')
        self.assertEqual(action, 'https://www2.citizenserve.com/Portal/PortalController')
        self.assertEqual(payload['Action'], 'DisplayCasesNPagging')
        self.assertEqual(payload['uniqueID'], 'abc123')
        self.assertEqual(payload['filetype'], 'Permit')
        self.assertEqual(payload['StartIndex'], '0')
        self.assertEqual(payload['EndIndex'], '30')

    def test_summarizes_result_rows_and_detail_links(self):
        summary = summarize_result_page(RESULT_HTML, 'https://www2.citizenserve.com/results')
        self.assertEqual(summary['title'], 'Search Results')
        self.assertIn('BP-1', summary['rows'][0]['cells'])
        self.assertIn('workorderID=42', summary['rows'][0]['links'][0]['href'])

if __name__ == '__main__':
    unittest.main()
