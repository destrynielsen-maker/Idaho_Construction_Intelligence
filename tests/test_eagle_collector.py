import unittest
from idaho_permits.classify import classify_permit
from idaho_permits.collectors.eagle import PORTAL_URL, permits_from_listing, _detail_scope, detail_links_from_shell, record_from_detail
from idaho_permits.models import Permit

LISTING='''<table><tr><th>Permit #</th><th>Date</th><th>Permit Type</th><th>Permit Address</th><th>Status</th></tr><tr><td><a href="/EAGLE/permit/600/1001">266108</a></td><td>08/04/2026</td><td>Building Commercial</td><td>839 East Winding Creek Drive</td><td>Pending Acceptance</td></tr><tr><td><a href="/EAGLE/permit/600/1002">266113</a></td><td>08/04/2026</td><td>Electrical Commercial</td><td>2826 S Eagle Rd Suite 120</td><td>Open</td></tr><tr><td><a href="/EAGLE/permit/600/1003">266099</a></td><td>08/03/2026</td><td>Building Residential</td><td>100 N New Home Way</td><td>Open</td></tr></table>'''
CARD_LISTING='''<div>Permit #:<a href="/EAGLE/permit/600/2001">266719</a></div><div>Date: 08/19/2026</div><div>Permit Type: Building Residential</div><div>Permit Address: 5634 W. Caldermill Ct.</div><div>Status: Online Submission</div><div>Inspection Request Currently Not Allowed</div><div>Permit #:<a href="/EAGLE/permit/600/2002">266718</a></div><div>Date: 08/19/2026</div><div>Permit Type: Electrical Residential</div><div>Permit Address: 100 Main St</div><div>Status: Online Submission</div><div>Inspection Request Currently Not Allowed</div><div>Permit #:<a href="/EAGLE/permit/600/2003">266712</a></div><div>Date: 08/19/2026</div><div>Permit Type: Building Residential</div><div>Permit Address: 6404 W SOLLAS CT</div><div>Status: Pending Acceptance</div><div>Request An Inspection</div>'''
SHELL='''<a href="https://portal.iworq.net/EAGLE/permit/600/29622638">View</a><a href="/EAGLE/permit/600/29622624">View</a><a href="/EAGLE/inspection-request/600/29622638">Inspection</a>'''
DETAIL='''<div>Permit #:</div><div>266719</div><div>Permit Date:</div><div>08/19/2026</div><div>Permit Type:</div><div>Building Residential</div><div>Use Class:</div><div>New Home- Single Family Residential</div><div>Description:</div><div>New Home</div><div>Permit Address:</div><div>5634 W. Caldermill Ct.</div><div>Subdivision:</div><div>Example Sub</div><div>Living Area Sqft:</div><div>2,603</div><div>Garage Square Feet:</div><div>1,158</div><div>Covered Patio Sqft:</div><div>618</div><div>Status:</div><div>Pending Acceptance</div><div>Contractors</div><div>TRESIDIO HOMES -</div><div>Builder</div><div>, 2973 N Eagle Rd</div><div>Property Information</div>'''
EMPTY_TYPE_DETAIL='''<div>Permit Number:</div><div>267346</div><div>Permit Date:</div><div>09/10/2026</div><div>Permit Type:</div><div>Use Class:</div><div>Remodel</div><div>Description:</div><div>Interior Remodel</div><div>Permit Address:</div><div>2651 E SNOCREEK DR</div><div>Status:</div><div>Property Information</div>'''

class EagleCollectorTests(unittest.TestCase):
    def test_uses_canonical_iworq_host(self): self.assertEqual(PORTAL_URL,'https://portal.iworq.net/EAGLE/permits/600')
    def test_listing_counts_all_source_records(self):
        rows=permits_from_listing(LISTING); self.assertEqual([r['permit_number'] for r in rows],['266108','266113','266099']); self.assertEqual(rows[0]['issued_date'],'2026-08-04')
    def test_responsive_cards_count_all_source_records(self):
        rows=permits_from_listing(CARD_LISTING); self.assertEqual([r['permit_number'] for r in rows],['266719','266718','266712']); self.assertEqual(rows[2]['status'],'Pending Acceptance')
    def test_extracts_current_detail_links_from_shell(self):
        links=detail_links_from_shell(SHELL); self.assertEqual(len(links),2); self.assertTrue(links[0].endswith('/EAGLE/permit/600/29622638'))
    def test_parses_labeled_detail_page_with_sales_fields(self):
        row=record_from_detail(DETAIL,'https://portal.iworq.net/EAGLE/permit/600/29622638')
        self.assertEqual(row['permit_number'],'266719')
        self.assertEqual(row['issued_date'],'2026-08-19')
        self.assertEqual(row['permit_type'],'Building Residential')
        self.assertEqual(row['use_class'],'New Home- Single Family Residential')
        self.assertEqual(row['scope'],'New Home')
        self.assertEqual(row['contractor'],'TRESIDIO HOMES')
        self.assertEqual(row['subdivision'],'Example Sub')
        self.assertEqual(row['living_area_sqft'],2603)
        self.assertEqual(row['garage_sqft'],1158)
        self.assertEqual(row['covered_patio_sqft'],618)
    def test_blank_detail_labels_do_not_borrow_next_label(self):
        row=record_from_detail(EMPTY_TYPE_DETAIL,'https://x')
        self.assertEqual(row['permit_type'],'')
        self.assertEqual(row['use_class'],'Remodel')
        self.assertEqual(row['status'],'')
    def test_extracts_scope_from_detail_labels(self): self.assertIn('New construction',_detail_scope('<div><b>Scope of Work:</b> New construction of a 12-unit apartment building</div>'))
    def test_eagle_new_home_use_class_qualifies_building_but_not_trade(self):
        building=Permit('ID','Eagle','1','2026-09-11','Building Residential','1 Main','x','https://x',project_name='single family dwelling',building_use='New Home- Single Family Residential')
        water=Permit('ID','Eagle','2','2026-09-11','Water Residential','1 Main','x','https://x',project_name='New Home',building_use='New Home- Single Family Residential')
        self.assertTrue(classify_permit(building).qualifies)
        self.assertEqual(building.classification,'SINGLE_FAMILY')
        self.assertFalse(classify_permit(water).qualifies)
    def test_building_qualifies_and_trades_do_not(self):
        new=Permit('ID','Eagle','1','2026-08-04','Building Residential','1 Main','x','https://x',building_use='New construction of single family dwelling')
        electrical=Permit('ID','Eagle','2','2026-08-04','Electrical Residential','2 Main','x','https://x',building_use='New Electrical Installation')
        water=Permit('ID','Eagle','3','2026-08-04','Water Commercial','3 Main','x','https://x',building_use='New commercial water meter')
        self.assertTrue(classify_permit(new).qualifies); self.assertFalse(classify_permit(electrical).qualifies); self.assertFalse(classify_permit(water).qualifies)

if __name__=='__main__': unittest.main()
