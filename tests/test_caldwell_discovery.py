import unittest
from idaho_permits.collectors.caldwell import report_links_from_page

HTML = '''
<html><body>
<a href="/files/building/april-2026.pdf">April 2026</a>
<a href="/files/building/may-2026.pdf">May 2026</a>
<a href="/files/building/june-2026.pdf">June 2026</a>
<a href="/not-a-report.html">June 2026 overview</a>
</body></html>
'''

class CaldwellDiscoveryTests(unittest.TestCase):
    def test_discovers_and_orders_official_monthly_pdf_reports(self):
        rows = report_links_from_page(HTML, 'https://www.cityofcaldwell.org/reports')
        self.assertEqual([r['label'] for r in rows], ['April 2026', 'May 2026', 'June 2026'])
        self.assertEqual(rows[-1]['report_date'], '2026-06-01')
        self.assertEqual(rows[-1]['url'], 'https://www.cityofcaldwell.org/files/building/june-2026.pdf')

    def test_ignores_non_pdf_month_links(self):
        rows = report_links_from_page('<a href="/june">June 2026</a>')
        self.assertEqual(rows, [])

if __name__ == '__main__':
    unittest.main()
