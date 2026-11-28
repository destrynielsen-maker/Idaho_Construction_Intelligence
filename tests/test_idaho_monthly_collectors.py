from datetime import date
from unittest import TestCase
from unittest.mock import patch

from idaho_permits.classify import classify_permit
from idaho_permits.collectors.blackfoot import BlackfootPermitCollector
from idaho_permits.collectors.garden_city import GardenCityPermitCollector
from idaho_permits.collectors.hailey import HaileyPermitCollector
from idaho_permits.collectors.twin_falls_county import _permit_type


PERIOD = date(2026, 10, 1)
TODAY = date(2026, 11, 27)
GARDEN_CSV = (
    'Permit Type,Permit No.,Issue Status,Issue Date,Description,Address,Project Value\n'
    'ResSFH,BLD-001,Issued,10/7/2026,New SFH construction,11 Test St,$400000\n'
    'CommNewConst,BLD-002,Issued,10/8/2026,New commercial office,12 Test St,$600000\n'
    'CommNewConst,BLD-003,Issued,10/9/2026,Tenant improvement,13 Test St,$200000\n'
    'ResSFH,BLD-004,Applied,,New SFH construction,14 Test St,$400000\n'
).encode()


class IdahoMonthlyCollectorTests(TestCase):
    def test_garden_csv_accepts_only_issued_and_explicit_new_scope(self):
        collector = GardenCityPermitCollector()
        for status_field in (b'Issue Status', b'Permit Status'):
            with self.subTest(status_field=status_field):
                source = GARDEN_CSV.replace(b'Issue Status', status_field)
                permits, observed = collector.parse_report(source, PERIOD, TODAY, collector.landing_url)
                self.assertEqual(len(observed), 3)
                self.assertEqual([p.permit_number for p in permits], ['BLD-001', 'BLD-002'])
                self.assertEqual([classify_permit(p).classification for p in permits], ['SINGLE_FAMILY', 'COMMERCIAL'])
                self.assertTrue(all(p.contractor is None and p.raw['issue_date_verified'] for p in permits))

    def test_monthly_discovery_preserves_latest_source_and_refuses_offsite_links(self):
        collector = GardenCityPermitCollector()
        oct_url = 'https://storage.googleapis.com/juniper-media-library/464/2026/11/October 2026.csv'
        index = (f'<a href="{oct_url}">October 2026</a>'
                 '<a href="https://example.org/report.csv">November 2026</a>')
        with patch('idaho_permits.collectors.monthly_reports._get', side_effect=[index.encode(), GARDEN_CSV]) as get:
            result = collector.collect(TODAY)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.args, (oct_url,))
        self.assertEqual(result.latest_issued_date, '2026-10-09')
        self.assertEqual(result.report_period_end, '2026-10-31')

    def test_garden_rejects_out_of_period_issued_record_and_duplicate_identity(self):
        collector = GardenCityPermitCollector()
        for source in (GARDEN_CSV.replace(b'10/7/2026', b'9/7/2026'),
                       GARDEN_CSV.replace(b'BLD-002', b'BLD-001')):
            with self.assertRaises(ValueError):
                collector.parse_report(source, PERIOD, TODAY, collector.landing_url)

    def test_blackfoot_reads_wrapped_scope_before_the_permit_row(self):
        collector = BlackfootPermitCollector()
        header = 'Record #  Record Type  Applicant Name  Address  Description  Square Feet  Date'
        row = 'RES-26-1  Residential Building Permit  Private Name  11 Test St  attached garage  1,200  10/7/2026'
        layout = 'Permit Issued\n' + header + '\n' + (' ' * header.index('Description')) + 'New stick built house\n' + row
        with patch('idaho_permits.collectors.blackfoot.pdf_layout', return_value=[layout]):
            permits, observed = collector.parse_report(b'', PERIOD, TODAY, collector.landing_url)
        self.assertEqual(len(observed), 1)
        self.assertEqual((permits[0].address, permits[0].area, permits[0].issued_date), ('11 Test St', '1200', '2026-10-07'))
        self.assertIsNone(permits[0].contractor)

    def test_hailey_ignores_summary_links_and_rejects_unlabeled_issue_dates(self):
        collector = HaileyPermitCollector()
        url = 'https://haileycityhall.org/wp-content/uploads/2026/11/October-summary.pdf'
        self.assertIsNone(collector.report_month('October Summary', url))
        with patch('idaho_permits.collectors.hailey.pdf_layout', return_value=['Permit # Permit Type Application Date Physical Address']):
            with self.assertRaisesRegex(ValueError, 'header'):
                collector.parse_report(b'', PERIOD, TODAY, url)

    def test_twin_falls_requires_description_to_match_primary_new_building(self):
        self.assertEqual(_permit_type('Single Family Residence', 'New', 'New single family home with attached garage'),
                         'New single-family building')
        self.assertEqual(_permit_type('Commercial Building', 'New', 'New freestanding storage building'),
                         'New commercial building')
        self.assertIsNone(_permit_type('Single Family Residence', 'New', 'Detached shop'))
        self.assertIsNone(_permit_type('Single Family Residence', 'New', 'Move original home onto new foundation'))
