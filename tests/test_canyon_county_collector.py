import unittest
from idaho_permits.classify import classify_permit
from idaho_permits.collectors.canyon_county import permit_from_tracker_attributes


class CanyonCountyCollectorTests(unittest.TestCase):
    def test_maps_active_current_application(self):
        row = {
            'BP_PermitNumber': 'BP2026-0651',
            'BP_ReceivedDate': 1787097600000,
            'BP_Status': 'Active',
            'BP_Approval_Status': 'In Progress',
            'BP_Classficiation': '101 Single Family Residence',
            'BP_SubType': 'Residential',
            'BP_ProjectInfo': 'NEW SFR W/ ATTACHED GARAGE',
            'BP_Address': '1234 S TEST RD',
            'BP_Contractor': 'Example Homes LLC',
            'BP_BuildValuation': '$650,000',
            'BP_ParcelNumber': 'R12345678',
        }
        p = permit_from_tracker_attributes(row)
        self.assertIsNotNone(p)
        self.assertEqual(p.jurisdiction, 'Canyon County')
        self.assertEqual(p.permit_number, 'BP2026-0651')
        self.assertEqual(p.issued_date, '2026-08-19')
        self.assertEqual(p.stage, 'APPLICATION')
        self.assertEqual(p.valuation, 650000.0)
        self.assertEqual(p.contractor, 'Example Homes LLC')
        self.assertTrue(classify_permit(p).qualifies)
        self.assertEqual(p.classification, 'SINGLE_FAMILY')

    def test_rejects_closed_or_not_approved_rows(self):
        base = {
            'BP_PermitNumber': 'BP2026-0001',
            'BP_ReceivedDate': 1787097600000,
            'BP_Classficiation': '101 Single Family Residence',
            'BP_SubType': 'Residential',
            'BP_ProjectInfo': 'NEW SFR W/ ATTACHED GARAGE',
        }
        self.assertIsNone(permit_from_tracker_attributes({**base,'BP_Status':'Closed','BP_Approval_Status':'Approved'}))
        self.assertIsNone(permit_from_tracker_attributes({**base,'BP_Status':'Active','BP_Approval_Status':'Not Approved'}))

    def test_active_addition_is_suppressed_by_shared_classifier(self):
        p = permit_from_tracker_attributes({
            'BP_PermitNumber': 'BP2026-0647',
            'BP_ReceivedDate': 1787011200000,
            'BP_Status': 'Active',
            'BP_Approval_Status': 'In Progress',
            'BP_Classficiation': '434 Additions, Alterations, Conversions - Residential',
            'BP_SubType': 'Residential',
            'BP_ProjectInfo': 'RESIDENTIAL ADDITION - 13X30 SUNROOM',
        })
        self.assertIsNotNone(p)
        self.assertFalse(classify_permit(p).qualifies)


if __name__ == '__main__':
    unittest.main()
