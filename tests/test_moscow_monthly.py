from datetime import date
import unittest

from idaho_permits.collectors.moscow import HEADER, MoscowPermitCollector
from idaho_permits.collectors.bannock import BannockCountyPermitCollector


OCTOBER = date(2026, 10, 1)
TODAY = date(2026, 11, 27)
LINK = 'https://www.ci.moscow.id.us/Archive.aspx?ADID=558'
PDF = 'https://www.ci.moscow.id.us/ArchiveCenter/ViewFile/Item/558'


def row(number, issue, permit_type):
    return '   '.join((number, issue, 'Test Owner', '1', 'Builder LLC', '10 Test Way', permit_type, '$125,000.00'))


def report(*rows):
    return ['\n'.join(('OCTOBER 2026', '   '.join(HEADER), *rows))]


class MoscowMonthlyTest(unittest.TestCase):
    def setUp(self):
        self.collector = MoscowPermitCollector()

    def test_archive_link_is_scoped_to_official_issued_file(self):
        title = '2026 October Building Permits Issued (PDF)'
        self.assertEqual(self.collector.report_month(title, LINK), OCTOBER)
        self.assertEqual(self.collector.report_url(LINK), PDF)
        self.assertIsNone(self.collector.report_month(title, LINK.replace('www.ci.moscow.id.us', 'example.com')))

    def test_issued_scope_filters_out_existing_building_work(self):
        pages = report(row('BLD2026-0001', '10/30/2026', 'NEW COMMERCIAL'),
                       row('BLD2026-0002', '10/29/2026', 'COMMERCIAL ALTERATION'))
        permits, identities = self.collector.parse_pages(pages, OCTOBER, TODAY, PDF)
        self.assertEqual(len(identities), 2)
        permit, = permits
        self.assertEqual((permit.jurisdiction, permit.stage, permit.valuation), ('Moscow', 'PERMITTED', 125000.0))
        self.assertTrue(permit.raw['issue_date_verified'])
        self.assertIsNone(permit.owner)

    def test_rejects_conflicting_identity_or_report_date(self):
        original = row('BLD2026-0001', '10/30/2026', 'NEW COMMERCIAL')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.collector.parse_pages(report(original, original), OCTOBER, TODAY, PDF)
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.collector.parse_pages(report(original.replace('10/30', '11/01')), OCTOBER, TODAY, PDF)


class BannockMonthlyTest(unittest.TestCase):
    def test_separates_county_dwellings_from_municipal_and_accessory_rows(self):
        collector = BannockCountyPermitCollector()
        pages = ['\n'.join((
            'Record Type    Record #    Issued Date    Applicant    Parcel    Project Description',
            'Residential    RDP-26-80    10/1/2026    Example    Parcel    New Dwelling    Single-Family    $700,000.00',
            'City of Arimo    A-26-2    10/6/2026    Example    Parcel    New Dwelling    Single-Family    $120,000.00',
            'Accessory    RAS-26-85    10/6/2026    Example    Parcel    Accessory Building    Shop    $30,000.00',
        ))]
        permits, observed = collector.parse_pages(pages, OCTOBER, TODAY, collector.landing_url)
        self.assertEqual(set(observed), {'RDP-26-80', 'RAS-26-85'})
        permit, = permits
        self.assertEqual(permit.address, '')
        self.assertEqual(permit.valuation, 700000.0)
