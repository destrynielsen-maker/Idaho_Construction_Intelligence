from pathlib import Path
from datetime import date
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from requests import Response

from idaho_permits import pipeline
from idaho_permits.collectors.coeur_dalene import CoeurDAleneCollector, REPORT_URL
from idaho_permits.models import Permit
from idaho_permits.storage import load_permits, save_permits


def response(status, content, content_type='text/html'):
    result = Response()
    result.status_code = status
    result.headers['Content-Type'] = content_type
    result._content = content
    result.url = REPORT_URL
    return result


MODULE = 'idaho_permits.collectors.coeur_dalene'


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 8, 28)



class TestCdaPublicSource(unittest.TestCase):
    def test_city_500_is_not_parsed(self):
        with patch(MODULE + '.requests.post', return_value=response(500, b'<html>Error</html>')), \
                patch(MODULE + '.pdf_text') as pdf:
            with self.assertRaisesRegex(RuntimeError, r'HTTP 500 .*no report parsed'):
                CoeurDAleneCollector().collect()
            pdf.assert_not_called()

    def test_html_200_even_with_pdf_mime_is_not_empty_success(self):
        with patch(MODULE + '.requests.post', return_value=response(200, b'<html>Error</html>', 'application/pdf')), \
                patch(MODULE + '.pdf_text') as pdf:
            with self.assertRaisesRegex(RuntimeError, r'did not return a PDF'):
                CoeurDAleneCollector().collect()
            pdf.assert_not_called()

    def test_pipeline_preserves_last_good_history_and_marks_error(self):
        collector = CoeurDAleneCollector()
        historical = Permit('ID', collector.name, 'Fixture-B', '2026-08-17',
                            'Duplex', 'Fixture Address', collector.name, REPORT_URL,
                            contractor='EXAMPLE HOMES LLC', first_seen_at='2026-08-18',
                            last_seen_at='2026-08-22')
        with TemporaryDirectory() as root, \
                patch.object(pipeline, 'COLLECTORS', [collector]), \
                patch(MODULE + '.requests.post', return_value=response(500, b'<html>Error</html>')):
            root = Path(root)
            store = root / 'data' / 'permits.json'
            save_permits(store, [historical], '2026-08-22')
            status, = pipeline.run(root)['sources']
            retained, = load_permits(store).values()
        self.assertEqual(status['status'], 'error')
        self.assertEqual(status['records_seen'], 0)
        self.assertEqual(retained.key, historical.key)
        self.assertEqual(retained.contractor, historical.contractor)
        self.assertEqual(retained.issued_date, historical.issued_date)
        self.assertEqual(retained.last_seen_at, historical.last_seen_at)

    def test_valid_pdf_magic_passes_to_existing_parser_despite_mime(self):
        text = '''
Permit Num:
Owner:
Address: 412 W LINDEN AVE Project: DUPLEX W/GARAGE
Issued: Valuation: Type:
152695-B
Duplex08/17/2026Example Owner LLC $450,000.00
Contractor: EXAMPLE HOMES LLC
'''
        content = b'%PDF-1.4 fixture; pdf_text mocked'
        with patch(MODULE + '.requests.post', return_value=response(200, content, 'application/octet-stream')), \
                patch(MODULE + '.pdf_text', return_value=text) as pdf, \
                patch(MODULE + '.date', FixedDate):
            results = CoeurDAleneCollector().collect()
            pdf.assert_called_once_with(content)
        self.assertEqual(len(results.permits), 1)
        permit, = results.permits
        self.assertEqual((permit.permit_number, permit.issued_date, permit.contractor), (
            '152695-B', '2026-08-17', 'EXAMPLE HOMES LLC'))
        self.assertEqual(permit.owner, 'Example Owner LLC')


if __name__ == '__main__':
    unittest.main()
