from datetime import date
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urljoin

from idaho_permits.classify import classify_permit
from idaho_permits.collectors.hayden import HaydenPermitCollector


NOW = date(2026, 11, 28)
MONTH = date(2026, 10, 1)
REPORT = 'https://cms2.revize.com/revize/haydenid/Docs/Government/Departments/Building/Reports/PermitsIssued10-2026.pdf'


def row(number, issued, contractor, address, value, fees, work):
    location = f'{contractor:<60}{address}'
    return f'{number:<25}{issued:<17}{location:<93}{value:<19}{fees:<17}{work}'


HEADER = row('Permit Number', 'Issued Date', 'Contractor', 'Address', 'Value', 'Amount Paid', 'Work Description')
SHELL = row('PB26-0348', '10/9/2026', '', '901 E SHORE AVE', '$1,382,022.00', '$17,102.00',
            'SHELL BUILDING TO BE BUILT OUT UNDER SEPARATE TENANT IMPROVEMENT(S)')
FOUNDATION = row('PB26-0437', '10/16/2026', 'BUILDER LLC', '123 E VISTA WAY', '$637,175.36', '$20,114.40',
                 'BUILDING C FOUNDATION WORK FINAL APPROVED UNDER PB23-0593')
RV_COVER = row('PB26-0456', '10/22/2026', 'BUILDER LLC', '912 N ALDER ST', '$295,000.00', '$3,441.49',
               'STORAGE BLDG 24 (RV COVER 1) PHASE 2')
TOWNHOME = row('PB26-0470', '10/16/2026', 'CITY REPORTED BUILDING CONTRACTOR COMPANY WITH LONG QUALIFIER ABCD',
               '1234 N MAIN ST', '$205,679.14', '$5,100.00', 'TOWNHOME LOT 9')


class HaydenTests(TestCase):
    def setUp(self):
        self.collector = HaydenPermitCollector()

    def test_discovery_binds_the_visible_label_to_the_official_document(self):
        relative = 'Docs/Government/Departments/Building/Reports/PermitsIssued10-2026.pdf?t=202611031526330'
        city_url = urljoin(self.collector.landing_url, relative)
        self.assertEqual(self.collector.report_month('Permits Issued 10 2026', city_url), MONTH)
        self.assertEqual(self.collector.report_url(city_url), REPORT + '?t=202611031526330')
        self.assertIsNone(self.collector.report_month('Permits Issued 09 2026', city_url))
        self.assertIsNone(self.collector.report_month('Permits Issued 10 2026', city_url.replace('haydenid.gov', 'example.org')))
        self.assertIsNone(self.collector.report_month('Permits Issued 10 2026', city_url + '&unexpected=1'))

    @patch('idaho_permits.collectors.hayden.pdf_layout')
    def test_observes_all_issued_rows_and_keeps_primary_building_scope(self, layout):
        layout.return_value = [
            '\n'.join(('October 2026 Permits Issued', HEADER, 'Com New Construction', SHELL, FOUNDATION, RV_COVER)),
            '\n'.join((HEADER, 'Res Townhome', TOWNHOME, 'Site',
                       row('PST26-0007', '10/21/2026', '', '555 N OAK ST', '$0.00', '$1,000.00', 'SITE WORK'))),
        ]
        permits, observed = self.collector.parse_report(b'%PDF-1.7', MONTH, NOW, REPORT)
        self.assertEqual(len(observed), 5)
        self.assertEqual([permit.permit_number for permit in permits], ['PB26-0348', 'PB26-0470'])
        self.assertEqual([classify_permit(permit).classification for permit in permits], ['COMMERCIAL', 'MULTIFAMILY'])
        self.assertTrue(all(permit.qualifies for permit in permits))
        self.assertEqual(permits[0].project_name, 'SHELL BUILDING')
        self.assertIn('SEPARATE TENANT IMPROVEMENT(S)', permits[0].raw['work_description'])
        self.assertIsNone(permits[0].contractor)
        self.assertEqual(permits[1].address, '1234 N MAIN ST')
        self.assertTrue(permits[1].contractor.endswith('ABCD'))
        self.assertEqual(permits[1].valuation, 205679.14)
        self.assertEqual(permits[1].source_url, REPORT + '#page=2')

    @patch('idaho_permits.collectors.hayden.pdf_layout')
    def test_bad_month_or_duplicate_identity_fails_closed(self, layout):
        for title, lines in (
            ('September 2026 Permits Issued', [SHELL]),
            ('October 2026 Permits Issued', [SHELL.replace('10/9/2026', '9/19/2026')]),
            ('October 2026 Permits Issued', [SHELL, SHELL]),
        ):
            layout.return_value = ['\n'.join((title, HEADER, 'Com New Construction', *lines))]
            with self.subTest(title=title, row_count=len(lines)), self.assertRaises(ValueError):
                self.collector.parse_report(b'%PDF-1.7', MONTH, NOW, REPORT)

    @patch('idaho_permits.collectors.monthly_reports._get')
    @patch('idaho_permits.collectors.hayden.pdf_layout')
    def test_public_monthly_discovery_returns_issued_progress(self, layout, get):
        get.side_effect = [b'<a href="Docs/Government/Departments/Building/Reports/PermitsIssued10-2026.pdf">'
                           b'Permits Issued 10 2026</a>', b'%PDF-1.7']
        layout.return_value = ['\n'.join(('October 2026 Permits Issued', HEADER, 'Com New Construction', SHELL))]
        result = self.collector.collect(NOW)
        self.assertEqual(get.call_args_list[-1].args, (REPORT,))
        self.assertEqual(result.report_period_end, '2026-10-31')
        self.assertTrue(result.progress_complete)
        self.assertEqual(result.progress[0]['stage'], 'issued')
        self.assertEqual(result.progress[0]['issue_date'], '2026-10-09')
        self.assertEqual(result.progress[0]['inspection_status'], 'unknown')
