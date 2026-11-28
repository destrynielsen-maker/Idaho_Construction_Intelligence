import unittest
from datetime import date
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from idaho_permits.classify import classify_permit
from idaho_permits.collectors.jerome import JeromePermitCollector


OCTOBER = date(2026, 10, 1)
SEPTEMBER = date(2026, 9, 1)
TODAY = date(2026, 11, 28)
ROOT = 'https://ci.jerome.id.us'
OCTOBER_PATH = '/DocumentCenter/View/1810/October-2026-Permit-Report'
SEPTEMBER_PATH = '/DocumentCenter/View/1799/September-2026-Issued-Permits'
HEADER = ['Permit number', 'Municipal address', 'Work type', 'Category', 'Work target', 'Owner',
          'Main Sq Ft:', 'Garage Sq Ft', 'Total Sq Ft', 'Issued date', 'Estimated\nProject Value:',
          'Permit fees total']


def row(number, category, target, *, work='New', issued='10/14/26', address='100 Example Road'):
    return [number, address, work, category, target, 'Example owner', '5,000', '0', '5,000', issued,
            '$ 666,500.00', '$ 1,200.00']


def document(rows, *, header=HEADER, extra_text=''):
    page = MagicMock()
    page.extract_tables.return_value = [[header, *rows]]
    page.extract_text.return_value = '\n'.join([*(row[0] for row in rows), extra_text])
    pdf = MagicMock()
    pdf.__enter__.return_value.pages = [page]
    return pdf


class JeromeTests(unittest.TestCase):
    def setUp(self):
        self.collector = JeromePermitCollector()

    def test_accepts_matching_official_document_paths_and_month_labels(self):
        self.assertEqual(self.collector.report_month('October 2026 Permit Report', ROOT + OCTOBER_PATH), OCTOBER)
        self.assertEqual(self.collector.report_month('September 2026 Issued Permits', ROOT + SEPTEMBER_PATH), SEPTEMBER)
        for url in (ROOT + OCTOBER_PATH + '?download=1', ROOT + OCTOBER_PATH + '#page=1',
                    'https://example.org' + OCTOBER_PATH, ROOT + SEPTEMBER_PATH):
            with self.subTest(url=url):
                self.assertIsNone(self.collector.report_month('October 2026 Permit Report', url))

    def test_repeat_is_limited_to_the_same_public_report_without_access_challenge(self):
        url = ROOT + SEPTEMBER_PATH
        for code, location, body, allowed in (
            (302, SEPTEMBER_PATH, b'', True),
            (302, OCTOBER_PATH, b'', False),
            (302, SEPTEMBER_PATH, b'Verify you are human', False),
            (403, SEPTEMBER_PATH, b'', False),
        ):
            with self.subTest(code=code, location=location, body=body):
                error = HTTPError(url, code, 'Publisher response', {'Location': location}, BytesIO(body))
                self.assertEqual(self.collector.can_repeat_report_request(error, url), allowed)
                error.close()

    def test_scopes_new_buildings_and_retains_published_dates_and_roles(self):
        data = [
            row('BLD-26-00001', 'Residential building', 'Single-family dwelling'),
            row('BLD-26-00002', 'Commercial building', 'Coffee Shop'),
            row('BLD-26-00003', 'Industrial building', 'Storage Building', issued='10/19/2026'),
            row('BLD-26-00004', 'Commercial building', 'Other - Foundation Only'),
            row('BLD-26-00005', 'Residential building', 'Single-family dwelling', work='Remodel'),
            row('BLD-26-00006', 'Accessory structures', 'Porch'),
            row('SGN-26-00001', 'Signs', 'Wall Sign'),
            row('ROW-26-00001', 'Right of way', 'ROW'),
        ]
        url = ROOT + OCTOBER_PATH
        with patch('pdfplumber.open', return_value=document(data)):
            permits, observed = self.collector.parse_report(b'%PDF-1.4', OCTOBER, TODAY, url)
        self.assertEqual(set(observed), {row[0] for row in data if row[0].startswith('BLD-')})
        self.assertEqual([p.permit_number for p in permits], ['BLD-26-00001', 'BLD-26-00002', 'BLD-26-00003'])
        self.assertEqual([classify_permit(p).classification for p in permits],
                         ['SINGLE_FAMILY', 'COMMERCIAL', 'COMMERCIAL'])
        permit = permits[-1]
        self.assertEqual(permit.key, 'ID:JEROME:BLD-26-00003')
        self.assertEqual((permit.city, permit.county), ('Jerome', 'Jerome'))
        self.assertEqual((permit.issued_date, permit.valuation), ('2026-10-19', 666500))
        self.assertEqual((permit.project_name, permit.source_url), ('Storage Building', url + '#page=1'))
        self.assertTrue(permit.raw['issue_date_verified'])
        self.assertIsNone(permit.owner)
        self.assertIsNone(permit.contractor)

    def test_rejects_changed_columns_lost_rows_duplicates_and_wrong_periods(self):
        valid = row('BLD-26-00003', 'Industrial building', 'Storage Building')
        broken = [
            document([valid], header=[*HEADER[:9], 'Application date', *HEADER[10:]]),
            document([valid], extra_text='BLD-26-00012'),
            document([valid, valid]),
            document([row(valid[0], valid[3], valid[4], issued='9/29/26')]),
        ]
        for pdf in broken:
            with patch('pdfplumber.open', return_value=pdf), self.assertRaises(ValueError):
                self.collector.parse_report(b'%PDF-1.4', OCTOBER, TODAY, ROOT + OCTOBER_PATH)

    def test_collect_sets_issued_only_progress_and_latest_building_issue_date(self):
        index = (f'<a href="{OCTOBER_PATH}">October 2026 Permit Report</a>'
                 f'<a href="{SEPTEMBER_PATH}">September 2026 Issued Permits</a>').encode()
        october = document([
            row('BLD-26-00003', 'Industrial building', 'Storage Building'),
            row('BLD-26-00004', 'Accessory structures', 'Porch', work='Addition', issued='10/20/26'),
            row('ROW-26-00001', 'Right of way', 'ROW', issued='10/29/26'),
        ])
        september = document([row('BLD-26-00002', 'Residential building', 'Single-family dwelling', issued='9/29/26')])
        for today, coverage_end in ((date(2026, 10, 30), '2026-10-20'), (TODAY, '2026-10-31')):
            with self.subTest(today=today), patch('pdfplumber.open', side_effect=[october, september]), \
                    patch('idaho_permits.collectors.monthly_reports._get', side_effect=[index, b'%PDF-', b'%PDF-']), \
                    patch('idaho_permits.collectors.monthly_reports.sleep') as wait:
                result = self.collector.collect(today)
                self.assertEqual(result.progress_coverage_end, coverage_end)
                self.assertEqual(wait.call_count, 2)
        self.assertEqual(result.latest_issued_date, '2026-10-20')
        self.assertEqual(result.report_period_end, '2026-10-31')
        self.assertTrue(result.progress_complete)
        self.assertEqual(result.progress_source_name, self.collector.source_name)
        self.assertEqual([p['permit_id'] for p in result.progress], ['BLD-26-00003', 'BLD-26-00002'])
        self.assertEqual(result.progress[0]['stage'], 'issued')
        self.assertEqual(result.progress[0]['issue_date'], '2026-10-14')
        self.assertIsNone(result.progress[0]['received_date'])
        self.assertEqual(result.progress[0]['inspection_status'], 'unknown')
