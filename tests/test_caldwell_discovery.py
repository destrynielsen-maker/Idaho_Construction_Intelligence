import unittest
from idaho_permits.collectors.caldwell import summarize_search_page

HTML = '''
<html><head><title>Citizenserve Online Portal</title></head><body>
<form method="post" action="/Portal/PortalController">
<input type="hidden" name="Action" value="doSearch" />
<select name="permit_type"><option value="">All</option><option value="RES">Residential</option></select>
<input type="text" name="permit_number" />
<button name="submitSearch" value="Search">Search</button>
</form>
<table><tr><th>Permit #</th><th>Address</th><th>Status</th></tr><tr><td>BP-1</td><td>1 Main</td><td>Issued</td></tr></table>
<a href="/Portal/PortalController?Action=showSearchPage&type=Permit">Search for permit</a>
</body></html>
'''

class CaldwellDiscoveryTests(unittest.TestCase):
    def test_captures_form_controls_tables_and_links(self):
        summary = summarize_search_page(HTML, 'https://www2.citizenserve.com/example')
        self.assertEqual(summary['title'], 'Citizenserve Online Portal')
        self.assertEqual(summary['forms'][0]['method'], 'post')
        names = [x['name'] for x in summary['forms'][0]['controls']]
        self.assertIn('Action', names)
        self.assertIn('permit_type', names)
        self.assertIn('permit_number', names)
        self.assertEqual(summary['tables'][0]['headers'], ['Permit #', 'Address', 'Status'])
        self.assertIn('permit', summary['links'][0]['label'].lower())

if __name__ == '__main__':
    unittest.main()
