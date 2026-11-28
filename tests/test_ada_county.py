from datetime import date, datetime
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from idaho_permits.collectors import ada_county


TODAY = date(2026, 11, 28)
LAYER = {
    'id': 0, 'name': 'Building Permits - All', 'capabilities': 'Map,Query,Data',
    'dateFieldsTimeReference': None, 'datesInUnknownTimezone': False,
    'fields': [{'name': name, 'type': kind} for name, kind in ada_county.FIELDS.items()],
}


def millis(iso):
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def application(oid=20, **changes):
    return {'attributes': {
        'OBJECTID': oid, 'APPFILE': '2600001-BP', 'AppDivision': 'BL', 'STATUS': 'Active',
        'APPStatus': 'A', 'APPAprvlStatus': 'IP', 'APPClosDate': None,
        'APPRcvdDate': millis('2026-11-28T02:45:00+00:00'), **changes,
    }}


class AdaCountyApplicationTests(unittest.TestCase):
    def collect(self, *responses):
        with patch.object(ada_county, '_get_json', side_effect=responses) as get, patch.object(ada_county, 'PAGE_SIZE', 2):
            return ada_county.AdaCountyApplicationCollector().collect(today=TODAY), get

    def test_progress_only_reconciles_pages_and_recent_closure(self):
        active = application()
        closed = application(21, APPFILE='2500002-BP', STATUS='Closed', APPStatus='C',
                             APPRcvdDate=millis('2025-12-08T13:15:00+00:00'),
                             APPClosDate=millis('2026-11-27T00:00:00+00:00'))
        result, get = self.collect(LAYER, {'count': 4}, {'objectIdFieldName': 'OBJECTID', 'objectIds': [22, 20, 21, 20]},
                                   {'features': [closed, active, active]}, {'features': [application(22)]})

        self.assertEqual(result.source, 'Ada County')
        self.assertEqual(result.permits, [])
        self.assertTrue(result.progress_complete)
        self.assertEqual(result.progress_coverage_end, '2026-11-27')
        self.assertEqual([call.kwargs['objectIds'] for call in get.call_args_list[3:]], ['20,21', '22'])
        self.assertIn("TIMESTAMP '2026-08-31 06:00:00'", get.call_args_list[1].kwargs['where'])
        self.assertIn("APPFILE <> '-1-BP'", get.call_args_list[1].kwargs['where'])
        by_id = {row['permit_id']: row for row in result.progress}
        self.assertEqual(len(by_id), 2)
        received = by_id['2600001-BP']
        self.assertEqual((received['stage'], received['received_date']), ('unknown', '2026-11-27'))
        self.assertEqual(received['source_status'], 'Active (APPStatus A, APPAprvlStatus IP)')
        self.assertEqual(received['inspection_status'], 'unknown')
        self.assertEqual(parse_qs(urlsplit(received['source_url']).query)['where'],
                         ["APPFILE = '2600001-BP' AND AppDivision = 'BL'"])
        self.assertEqual((by_id['2500002-BP']['stage'], by_id['2500002-BP']['closed_date']), ('closed', '2026-11-27'))
        for row in by_id.values():
            self.assertNotIn('issue_date', row)
            self.assertNotIn('issued_flag', row)

    def test_closed_stage_requires_agreeing_status_and_plausible_civil_date(self):
        closure = millis('2026-11-28T00:00:00+00:00')
        for status, code, when in [('Active', 'A', closure), ('Closed', 'A', closure),
                                   ('Closed', 'C', None), ('Closed', 'C', closure + 3600_000),
                                   ('Closed', 'C', millis('2026-11-26T00:00:00+00:00'))]:
            with self.subTest(status=status, code=code, when=when):
                result, _ = self.collect(LAYER, {'count': 1}, {'objectIdFieldName': 'OBJECTID', 'objectIds': [20]},
                                         {'features': [application(STATUS=status, APPStatus=code, APPClosDate=when)]})
                self.assertEqual(result.progress[0]['stage'], 'unknown')
                self.assertIsNone(result.progress[0]['closed_date'])

    def test_explicit_empty_result_is_complete(self):
        result, get = self.collect(LAYER, {'count': 0}, {'objectIdFieldName': 'OBJECTID', 'objectIds': None})
        self.assertTrue(result.progress_complete)
        self.assertEqual(result.progress, [])
        self.assertIsNone(result.progress_coverage_end)
        self.assertEqual(get.call_count, 3)

    def test_rejects_scope_or_integrity_changes(self):
        ids = {'objectIdFieldName': 'OBJECTID', 'objectIds': [20, 21]}
        good = application()
        failures = [
            ({**LAYER, 'datesInUnknownTimezone': True},),
            (LAYER, {'count': ada_county.MAX_RECORDS + 1}),
            (LAYER, {'count': 2}, {**ids, 'objectIds': [20]}),
            (LAYER, {'count': 2}, ids, {'features': [good]}),
            (LAYER, {'count': 2}, ids, {'features': [good, good]}),
            (LAYER, {'count': 2}, ids, {'features': [good, application(23)]}),
            (LAYER, {'count': 2}, ids, {'features': [good, application(21, APPFILE='2600002-X_IMP')]}),
            (LAYER, {'count': 2}, ids, {'features': [good, application(21, STATUS='In Process', APPStatus='N')]}),
        ]
        for index, responses in enumerate(failures):
            with self.subTest(case=index), self.assertRaises(ValueError):
                self.collect(*responses)
