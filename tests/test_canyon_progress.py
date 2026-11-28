from datetime import date
import unittest
from urllib.parse import parse_qs, urlsplit

from idaho_permits.collectors.canyon_progress import progress_from_tracker_attributes


TODAY = date(2026, 11, 27)
IN_PROGRESS = {'BP_Status': 'Active', 'BP_Approval_Status': 'In Progress'}


class CanyonProgressTests(unittest.TestCase):
    def test_approved_case_with_no_issuance(self):
        result = progress_from_tracker_attributes({**IN_PROGRESS, 'BP_PermitNumber': 'BP2026-0879',
            'BP_ReceivedDate': 1795046400000, 'BP_Building_Review_Result': 'Approved',
            'BP_Building_Review_ResultDate': 1795046400000}, TODAY)
        self.assertEqual((result['received_date'], result['review_date']), ('2026-11-19', '2026-11-19'))
        self.assertEqual(result['stage'], 'review_approved_no_issue')
        self.assertIsNone(result['issued_flag'])
        self.assertIsNone(result['issue_date'])
        self.assertEqual(result['inspection_status'], 'unknown')

    def test_issue_evidence_overrides_generic_source_status(self):
        result = progress_from_tracker_attributes({**IN_PROGRESS, 'BP_PermitNumber': 'BP2026-0839',
            'BP_ReceivedDate': 1793577600000, 'BP_Building_Review_Result': 'Approved',
            'BP_Building_Review_ResultDate': 1793577600000, 'PemitIssued': 'Permit Issued',
            'PermitIssuedDate': 1794441600000}, TODAY)
        self.assertEqual(result['stage'], 'issued')
        self.assertEqual((result['received_date'], result['review_date'], result['issue_date']),
                         ('2026-11-02', '2026-11-02', '2026-11-12'))
        self.assertTrue(result['issued_flag'])
        self.assertEqual(result['source_status'], 'Active / In Progress')
        self.assertEqual(parse_qs(urlsplit(result['source_url']).query)['where'], ["BP_PermitNumber = 'BP2026-0839'"])

    def test_only_explicit_closure_and_plausible_dates_are_supported(self):
        row = {'BP_PermitNumber': 'BP2026-0001', 'BP_ReceivedDate': 1793577600000,
               'PermitIssuedDate': 1790006400000, 'BP_Building_Review_Result': 'In Progress'}
        under_review = progress_from_tracker_attributes({**row, **IN_PROGRESS}, TODAY)
        self.assertIsNone(under_review['issue_date'])
        self.assertEqual(under_review['stage'], 'application_under_review')
        expired = progress_from_tracker_attributes({**row, 'BP_Status': 'Expired'}, TODAY)
        self.assertEqual(expired['stage'], 'unknown')
        closed = progress_from_tracker_attributes({**row, 'BP_Status': 'Closed', 'BP_DateClosed': 1794441600000}, TODAY)
        self.assertEqual((closed['stage'], closed['closed_date']), ('closed', '2026-11-12'))

    def test_valid_issue_date_can_be_recorded_independently_of_missing_flag(self):
        row = {**IN_PROGRESS, 'BP_PermitNumber': 'BP2026-0002', 'BP_ReceivedDate': 1793577600000,
               'PermitIssuedDate': 1794441600000}
        progress = progress_from_tracker_attributes(row, TODAY)
        self.assertEqual((progress['stage'], progress['issue_date'], progress['issued_flag']),
                         ('issued', '2026-11-12', None))
        malformed = progress_from_tracker_attributes({**row, 'BP_ReceivedDate': 'Invalid'}, TODAY)
        self.assertIsNone(malformed['issue_date'])
