import unittest
from idaho_permits.collectors.boise import permit_from_feature


class BoiseCollectorTests(unittest.TestCase):
    def test_maps_official_development_tracker_feature(self):
        feature = {
            'attributes': {
                'RecordID': 'PLN24-00123',
                'RecordName': 'River District Apartments',
                'Status': 'Applications in Review',
                'AddToTrackerDate': 1722470400000,
                'RecordType': 'Planned Unit Development',
                'PropertyAddress': '100 W Main St',
                'ComprehensivePlanningArea': 'Downtown',
                'Website': 'https://permits.cityofboise.org/example',
                'Description': 'New construction of a 120-unit multifamily apartment development',
            }
        }
        permit = permit_from_feature(feature)
        self.assertIsNotNone(permit)
        self.assertEqual(permit.permit_number, 'PLN24-00123')
        self.assertEqual(permit.issued_date, '2024-08-01')
        self.assertEqual(permit.jurisdiction, 'Boise')
        self.assertEqual(permit.stage, 'PLANNING')
        self.assertEqual(permit.county, 'Ada')
        self.assertTrue(permit.building_use.startswith('New construction'))

    def test_drops_feature_without_stable_record_id(self):
        self.assertIsNone(permit_from_feature({'attributes': {'RecordName': 'Missing ID'}}))


if __name__ == '__main__':
    unittest.main()
