import unittest
from datetime import date
from unittest.mock import patch

from idaho_permits.classify import classify_permit
from idaho_permits.collectors.twin_falls_city import TwinFallsCityPermitCollector


OCTOBER = date(2026, 10, 1)
TODAY = date(2026, 11, 28)
URL = 'https://www.tfid.org/Archive/ViewFile/Item/3493'


def page(body, number=1, count=1, bounds='10/1/2026 to 11/1/2026'):
    return f'  Permit List\n\n  {bounds}\n\n{body}\n\n   Page {number} of {count}\n'


def row(number, kind, work, contractor='Example Contractor LLC', issued='10/27/2026'):
    return (
        f'Permit #: {number}   {kind}Application Date: 9/30/2026Issued Date: {issued}\n'
        'Permit Address: 100 Example Avenue   Valuation: $225,000.00   Fees Paid: $1,000.00\n'
        f'Owner: Unpublished      Contractor: {contractor}\n'
        f'                         Description of Work: {work}\n'
    )


DETACHED = 'Single-family Residential (detached)'


class TwinFallsCityTests(unittest.TestCase):
    def setUp(self):
        self.collector = TwinFallsCityPermitCollector()

    def test_normalizes_official_archive_labels_only(self):
        self.assertEqual(self.collector.report_month('Most Recent Item 2026 October', URL), OCTOBER)
        self.assertEqual(self.collector.report_month('October 2026', URL), OCTOBER)
        self.assertIsNone(self.collector.report_month('October 2026', URL + '?download=1'))
        self.assertIsNone(self.collector.report_month('October 2026', URL.replace('www.tfid.org', 'example.org')))
        self.assertIsNone(self.collector.report_month('Monthly Summary', URL))

    def test_reconciles_subtotal_across_pages_and_qualifies_explicit_dwelling_only(self):
        first = row('26-1001', DETACHED, 'Single Family Dwelling with attached garage')
        second = row('26-1002', DETACHED, '100 Example Avenue', contractor='OWNER/BUILDER')
        duplex = row('26-1003', 'Duplex (2-family dwelling on one lot)', 'Parent')
        spare = row('26-1004', DETACHED, 'Repair existing single family dwelling')
        layouts = [page(first + second + spare, 1, 2),
                   page('Total # of Permits: 3\n' + duplex + 'Total # of Permits: 1', 2, 2)]
        with patch('idaho_permits.collectors.twin_falls_city.pdf_layout', return_value=layouts):
            permits, observed = self.collector.parse_report(b'%PDF-1.4', OCTOBER, TODAY, URL)
        self.assertEqual(set(observed), {'26-1001', '26-1002', '26-1003', '26-1004'})
        self.assertEqual([p.permit_number for p in permits], ['26-1001'])
        permit = permits[0]
        self.assertTrue(classify_permit(permit).qualifies)
        self.assertEqual(permit.key, 'ID:TWIN FALLS:26-1001')
        self.assertEqual((permit.county, permit.city), ('Twin Falls', 'Twin Falls'))
        self.assertEqual(permit.issued_date, '2026-10-27')
        self.assertEqual(permit.raw['application_date'], '2026-09-30')
        self.assertEqual(permit.contractor, 'Example Contractor LLC')
        self.assertEqual(permit.raw['contractor_role'], 'City-reported contractor')
        self.assertEqual(permit.valuation, 225000)
        self.assertEqual(permit.source_url, URL + '#page=1')
        self.assertIsNone(permit.owner)

    def test_rejects_count_date_identity_and_page_mismatches(self):
        valid = row('26-1001', DETACHED, 'New single family dwelling')
        malformed = [
            page(valid + 'Total # of Permits: 2'),
            page(valid + valid + 'Total # of Permits: 2'),
            page(valid.replace('10/27/2026', '11/1/2026') + 'Total # of Permits: 1'),
            page(valid + 'Total # of Permits: 1', bounds='9/1/2026 to 10/1/2026'),
            page(valid + 'Total # of Permits: 1', 2, 2),
            page(valid),
        ]
        for layout in malformed:
            with self.subTest(layout=layout), patch('idaho_permits.collectors.twin_falls_city.pdf_layout',
                                                   return_value=[layout]), self.assertRaises(ValueError):
                self.collector.parse_report(b'%PDF-1.4', OCTOBER, TODAY, URL)

    def test_collect_exposes_qualified_issued_progress_without_owner_attribution(self):
        layout = page(row('26-1001', DETACHED, 'Single Family Dwelling', contractor='OWNER/BUILDER')
                      + row('26-1002', DETACHED, 'Site shorthand') + 'Total # of Permits: 2')
        index = b'<a href="/Archive/ViewFile/Item/3493">Most Recent Item 2026 October</a>'
        with patch('idaho_permits.collectors.twin_falls_city.pdf_layout', return_value=[layout]), \
                patch('idaho_permits.collectors.monthly_reports._get', side_effect=[index, b'%PDF-1.4']), \
                patch('idaho_permits.collectors.monthly_reports.sleep') as wait:
            result = self.collector.collect(TODAY)
        self.assertEqual(self.collector.crawl_delay, 10)
        wait.assert_called_once()
        self.assertIsNone(result.permits[0].contractor)
        self.assertNotIn('contractor_role', result.permits[0].raw)
        self.assertEqual(result.report_period_end, '2026-10-31')
        self.assertEqual(result.latest_issued_date, '2026-10-27')
        self.assertTrue(result.progress_complete)
        self.assertEqual([row['permit_id'] for row in result.progress], ['26-1001'])
        self.assertEqual(result.progress[0]['stage'], 'issued')
        self.assertEqual(result.progress[0]['issue_date'], '2026-10-27')
        self.assertIsNone(result.progress[0]['received_date'])

    def test_discovery_ignores_unselected_archive_revisions_but_rejects_selected_conflicts(self):
        index = (
            b'<a href="/Archive/ViewFile/Item/3493">Most Recent Item 2026 October</a>'
            b'<a href="/Archive/ViewFile/Item/3492">September 2026</a>'
            b'<a href="/Archive/ViewFile/Item/3304">July 2023</a>'
            b'<a href="/Archive/ViewFile/Item/3305">July 2023</a>'
        )
        october = page(row('26-1001', DETACHED, 'Single Family Dwelling') + 'Total # of Permits: 1')
        september_body = row('26-1000', DETACHED, 'Single Family Dwelling', issued='9/30/2026')
        september = page(september_body + 'Total # of Permits: 1', bounds='9/1/2026 to 10/1/2026')
        with patch('idaho_permits.collectors.twin_falls_city.pdf_layout', side_effect=[[october], [september]]), \
                patch('idaho_permits.collectors.monthly_reports._get', side_effect=[index, b'%PDF-1.4', b'%PDF-1.4']), \
                patch('idaho_permits.collectors.monthly_reports.sleep'):
            result = self.collector.collect(TODAY)
        self.assertEqual({p.permit_number for p in result.permits}, {'26-1000', '26-1001'})
        conflict = index + b'<a href="/Archive/ViewFile/Item/3500">October 2026</a>'
        with patch('idaho_permits.collectors.monthly_reports._get', return_value=conflict) as fetch, \
                self.assertRaisesRegex(ValueError, 'Conflicting publisher report links'):
            self.collector.collect(TODAY)
        fetch.assert_called_once()
