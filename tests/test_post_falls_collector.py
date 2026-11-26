import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests

from idaho_permits.classify import classify_permit
from idaho_permits.collectors.post_falls import QUERY_URL, PostFallsPermitCollector, permit_from_attributes


class PostFallsCollectorTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 11)
        self.cutoff = date(2026, 6, 14)

    def attrs(self, **overrides):
        data = {
            'OBJECTID': 1,
            'DESCRIPTION': None,
            'USER_Record__': 'BLDR-26-629',
            'USER_Valuation': 349006.02,
            'USER_Record_Type': 'Residential Building Permit',
            'USER_Permit_License_Issued_Date': 1787616000000,
            'USER_Type_of_Work': 'New Construction',
            'USER_Building_Type': 'Single-Family',
            'USER_Location': '3513 N SEGAR LOOP, POST FALLS ID 83854',
            'USER_Record_Status': 'Active',
            'USER_Amount': 5000,
        }
        data.update(overrides)
        return data

    def test_single_family_maps_and_qualifies(self):
        p = permit_from_attributes(self.attrs(), self.cutoff, self.today)
        self.assertIsNotNone(p)
        self.assertEqual(p.issued_date, '2026-08-25')
        self.assertEqual(p.valuation, 349006.02)
        classify_permit(p)
        self.assertTrue(p.qualifies)
        self.assertEqual(p.classification, 'SINGLE_FAMILY')

    def test_duplex_maps_to_multifamily_with_two_units(self):
        p = permit_from_attributes(self.attrs(
            USER_Record__='BLDR-26-632',
            USER_Building_Type='Duplex',
            USER_Valuation=340157.56,
        ), self.cutoff, self.today)
        self.assertIsNotNone(p)
        self.assertEqual(p.units, 2)
        classify_permit(p)
        self.assertTrue(p.qualifies)
        self.assertEqual(p.classification, 'MULTIFAMILY')

    def test_commercial_ground_up_maps_and_qualifies(self):
        p = permit_from_attributes(self.attrs(
            USER_Record__='BLDC-26-50',
            USER_Record_Type='Commercial Building Permit',
            USER_Building_Type='Commercial',
            USER_Valuation=12000000,
        ), self.cutoff, self.today)
        self.assertIsNotNone(p)
        classify_permit(p)
        self.assertTrue(p.qualifies)
        self.assertEqual(p.classification, 'COMMERCIAL')
        self.assertEqual(p.score, 45)

    def test_accessory_addition_roofing_and_expired_are_rejected(self):
        cases = [
            self.attrs(USER_Building_Type='Accessory Structure'),
            self.attrs(USER_Type_of_Work='Addition'),
            self.attrs(USER_Type_of_Work='Roofing/Siding/Windows'),
            self.attrs(USER_Record_Status='Expired/Cancelled'),
        ]
        for attrs in cases:
            self.assertIsNone(permit_from_attributes(attrs, self.cutoff, self.today))

    def test_record_type_mismatch_fails_closed(self):
        attrs = self.attrs(USER_Record_Type='Commercial Building Permit', USER_Building_Type='Single-Family')
        self.assertIsNone(permit_from_attributes(attrs, self.cutoff, self.today))

    def test_outside_rolling_window_is_rejected(self):
        attrs = self.attrs(USER_Permit_License_Issued_Date=1781222400000)  # 2026-06-12 UTC
        self.assertIsNone(permit_from_attributes(attrs, self.cutoff, self.today))


    def response(self, *records):
        result = Mock()
        result.json.return_value = {'features': [{'attributes': row} for row in records]}
        return result

    @patch('idaho_permits.collectors.post_falls.date', wraps=date)
    @patch('idaho_permits.collectors.post_falls.requests.get')
    def test_retries_only_transient_timeouts_and_preserves_response(self, get, clock):
        clock.today.return_value = self.today
        parser_rows = [self.attrs(), self.attrs(USER_Record__='excluded', USER_Type_of_Work='Addition')]
        response = self.response(*parser_rows)
        get.return_value = response
        baseline = PostFallsPermitCollector().collect()
        for exc in (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout):
            with self.subTest(exc=exc):
                get.reset_mock()
                get.side_effect = [exc(), response]
                result = PostFallsPermitCollector().collect()
                self.assertEqual(get.call_count, 2)
                self.assertEqual(get.call_args_list[0], get.call_args_list[1])
                self.assertEqual(get.call_args.args, (QUERY_URL,))
                self.assertEqual(get.call_args.kwargs['timeout'], 60)
                self.assertEqual(result.note, baseline.note)
                self.assertEqual([p.to_dict() for p in result.permits], [p.to_dict() for p in baseline.permits])

    @patch('idaho_permits.collectors.post_falls.date', wraps=date)
    @patch('idaho_permits.collectors.post_falls.requests.get')
    def test_latest_authoritative_issue_is_not_just_latest_qualified_lead(self, get, clock):
        clock.today.return_value = date(2026, 11, 26)
        get.return_value = self.response(
            self.attrs(USER_Permit_License_Issued_Date='2026-11-03'),
            self.attrs(USER_Record__='excluded', USER_Type_of_Work='Addition',
                       USER_Permit_License_Issued_Date='2026-11-04'),
            self.attrs(USER_Record__='invalid-future', USER_Permit_License_Issued_Date='2027-11-01'))
        result = PostFallsPermitCollector().collect()
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.latest_issued_date, '2026-11-04')
        self.assertIn('newest issued permit 2026-11-04', result.note)
        self.assertEqual([permit.issued_date for permit in result.permits], ['2026-11-03'])

    @patch('idaho_permits.collectors.post_falls.requests.get')
    def test_no_retry_on_http_or_non_timeout_transport_errors(self, get):
        for code in (403, 429, 500):
            with self.subTest(code=code):
                response = requests.Response()
                response.status_code = code
                response.url = QUERY_URL
                get.reset_mock()
                get.return_value = response
                with self.assertRaises(requests.exceptions.HTTPError):
                    PostFallsPermitCollector().collect()
                get.assert_called_once()
        get.reset_mock()
        get.side_effect = requests.exceptions.ConnectionError('non-timeout')
        with self.assertRaises(requests.exceptions.ConnectionError):
            PostFallsPermitCollector().collect()
        get.assert_called_once()

    @patch('idaho_permits.collectors.post_falls.PAGE_SIZE', 1)
    @patch('idaho_permits.collectors.post_falls.date', wraps=date)
    @patch('idaho_permits.collectors.post_falls.requests.get')
    def test_one_retry_total_and_no_partial_result(self, get, clock):
        clock.today.return_value = self.today
        get.side_effect = [requests.exceptions.ReadTimeout(), self.response(self.attrs()),
                           requests.exceptions.ConnectTimeout()]
        with self.assertRaises(requests.exceptions.ConnectTimeout):
            PostFallsPermitCollector().collect()
        self.assertEqual([c.kwargs['params']['resultOffset'] for c in get.call_args_list], [0, 0, 1])


if __name__ == '__main__':
    unittest.main()
