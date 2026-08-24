import unittest
from idaho_permits.classify import classify_permit
from idaho_permits.collectors.canyon_county import permit_from_attributes


class CanyonCountyCollectorTests(unittest.TestCase):
    def test_maps_official_issued_permit_fields(self):
        row = {
            'PermitIssued': 1786579200000,
            'PermitNum': 'BP-26-01234',
            'Classification': 'Residential',
            'Address': '1234 S TEST RD',
            'ProjectInfo': 'New single family dwelling with attached garage',
            'Contractor': 'Example Homes LLC',
            'Subdivision': 'Example Estates',
            'Valuation': '$650,000',
            'Status': 'Issued',
            'ParcelNum1': 'R12345678',
        }
        p = permit_from_attributes(row)
        self.assertIsNotNone(p)
        self.assertEqual(p.jurisdiction, 'Canyon County')
        self.assertEqual(p.permit_number, 'BP-26-01234')
        self.assertEqual(p.issued_date, '2026-08-13')
        self.assertEqual(p.stage, 'PERMITTED')
        self.assertEqual(p.valuation, 650000.0)
        self.assertEqual(p.contractor, 'Example Homes LLC')
        self.assertTrue(classify_permit(p).qualifies)
        self.assertEqual(p.classification, 'SINGLE_FAMILY')

    def test_requires_real_permit_number_and_issue_date(self):
        self.assertIsNone(permit_from_attributes({'PermitIssued': 1786579200000}))
        self.assertIsNone(permit_from_attributes({'PermitNum': 'BP-26-1'}))

    def test_remodel_does_not_qualify(self):
        p = permit_from_attributes({
            'PermitIssued': 1786579200000,
            'PermitNum': 'BP-26-09999',
            'Classification': 'Residential',
            'Address': '10 TEST ST',
            'ProjectInfo': 'Residential remodel and alteration',
        })
        self.assertFalse(classify_permit(p).qualifies)


if __name__ == '__main__':
    unittest.main()
