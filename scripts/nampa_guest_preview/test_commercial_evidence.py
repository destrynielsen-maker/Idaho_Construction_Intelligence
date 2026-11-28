import unittest
from datetime import date

from commercial_evidence import PERMIT_TYPE, review, scope_from_layout


START = date(2026, 11, 18)
END = date(2026, 11, 24)
CASE = {
    'permit_id': 'COM-10000-2026',
    'permit_type': PERMIT_TYPE,
    'status': 'Issued',
    'issue_date': '2026-11-18',
    'valuation_cents': 25_000_000,
    'case_url': 'https://nampaid-energovpub.tylerhost.net/Apps/SelfService#/permit/00000000-0000-0000-0000-000000000001',
}
SCOPE = {
    'permit_id': CASE['permit_id'],
    'report_url': 'https://www.cityofnampa.us/DocumentCenter/View/1/Commercial-Permit---Plan-Review-Status---July',
    'page': 3,
    'scope': 'Construct a one-story metal building with offices and detailing bays.',
}


class CommercialEvidenceTest(unittest.TestCase):
    def test_issued_case_and_matching_new_building_scope(self):
        result = review([CASE], [SCOPE], START, END)[0]
        self.assertEqual(result['decision'], 'new_building_candidate')
        self.assertEqual(result['valuation_cents'], 25_000_000)
        self.assertEqual(result['scope_evidence']['page'], 3)

    def test_amenity_and_tenant_work_do_not_qualify(self):
        for scope in ('Pool amenity storage and changing rooms.',
                      'Construct a new building addition for a tenant improvement.'):
            with self.subTest(scope=scope):
                result = review([CASE], [{**SCOPE, 'scope': scope}], START, END)[0]
                self.assertEqual(result['decision'], 'excluded_scope')

    def test_title_only_or_unmatched_scope_stays_pending(self):
        case = {**CASE, 'project_name': 'New Office Building'}
        other = {**SCOPE, 'permit_id': 'COM-10001-2026'}
        self.assertEqual(review([case], [other], START, END)[0]['decision'], 'needs_scope_evidence')

    def test_rejects_bad_dates_status_origin_and_duplicate_ids(self):
        for changed in ({'issue_date': '2026-11-25'}, {'status': 'Ready to Issue'},
                        {'case_url': 'https://example.org/permit'}, {'valuation_cents': True}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                review([{**CASE, **changed}], [SCOPE], START, END)
        with self.assertRaises(ValueError):
            review([CASE, CASE], [SCOPE], START, END)
        with self.assertRaises(ValueError):
            review([CASE], [SCOPE, SCOPE], START, END)

    def test_reads_only_requested_permit_scope_in_numbered_report(self):
        header = f'{"Permit #":32}{"Scope of Work":45}Stated'
        rows = [
            'Commercial Permit - Plan Review Status      City of Nampa', header,
            f'{"COM-10000-2026 07/15/2026":32}{"Construct a one-story metal building":45}$250,000.00',
            f'{"":32}with offices and detailing bays.',
            f'{"COM-10001-2026 07/16/2026":32}Tenant improvement.',
            'Page 3 of 6',
        ]
        self.assertEqual(scope_from_layout('\n'.join(rows), {CASE['permit_id']}), [
            (CASE['permit_id'], 'Construct a one-story metal building with offices and detailing bays.'),
        ])
        rows[1] = rows[1].replace('Scope of Work', 'Description')
        with self.assertRaisesRegex(ValueError, 'Unrecognized Nampa report'):
            scope_from_layout('\n'.join(rows), {CASE['permit_id']})
