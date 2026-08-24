import unittest
from idaho_permits.classify import classify_permit
from idaho_permits.collectors.eagle import PORTAL_URL, permits_from_listing, _detail_scope
from idaho_permits.models import Permit


LISTING = '''
<table>
<tr><th>Permit #</th><th>Date</th><th>Permit Type</th><th>Permit Address</th><th>Status</th></tr>
<tr><td><a href="/EAGLE/permit/600/1001">266108</a></td><td>08/04/2026</td><td>Building Commercial</td><td>839 East Winding Creek Drive</td><td>Pending Acceptance</td></tr>
<tr><td><a href="/EAGLE/permit/600/1002">266113</a></td><td>08/04/2026</td><td>Electrical Commercial</td><td>2826 S Eagle Rd Suite 120</td><td>Open</td></tr>
<tr><td><a href="/EAGLE/permit/600/1003">266099</a></td><td>08/03/2026</td><td>Building Residential</td><td>100 N New Home Way</td><td>Open</td></tr>
</table>
'''


class EagleCollectorTests(unittest.TestCase):
    def test_uses_canonical_iworq_host(self):
        self.assertEqual(PORTAL_URL, 'https://portal.iworq.net/EAGLE/permits/600')

    def test_listing_keeps_only_building_permits(self):
        rows = permits_from_listing(LISTING)
        self.assertEqual([r['permit_number'] for r in rows], ['266108', '266099'])
        self.assertEqual(rows[0]['issued_date'], '2026-08-04')
        self.assertTrue(rows[0]['detail_url'].endswith('/EAGLE/permit/600/1001'))

    def test_extracts_scope_from_detail_labels(self):
        html = '<div><b>Scope of Work:</b> New construction of a 12-unit apartment building</div>'
        scope = _detail_scope(html)
        self.assertIn('New construction', scope)

    def test_new_eagle_build_qualifies_but_remodel_does_not(self):
        new = Permit('ID','Eagle','1','2026-08-04','Building Residential','1 Main','x','https://x',building_use='New construction of single family dwelling')
        remodel = Permit('ID','Eagle','2','2026-08-04','Building Residential','2 Main','x','https://x',building_use='Residential remodel and alteration')
        self.assertTrue(classify_permit(new).qualifies)
        self.assertFalse(classify_permit(remodel).qualifies)


if __name__ == '__main__':
    unittest.main()
