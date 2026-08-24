import unittest
from idaho_permits.classify import classify_permit
from idaho_permits.collectors.boise import permit_from_feature


class BoiseQualityGuardTests(unittest.TestCase):
    def test_live_shape_conversion_is_suppressed(self):
        permit = permit_from_feature({
            'attributes': {
                'RecordID': 'PLN26-00595',
                'RecordName': '1208 W FORT ST',
                'Status': 'Applications in Review',
                'AddToTrackerDate': 1786708800000,
                'RecordType': 'Project',
                'PropertyAddress': '1208 W FORT ST',
                'Description': 'Conversion of triplex to duplex and minor exterior modifications',
            }
        })
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertEqual(permit.stage, 'PLANNING')
        self.assertFalse(permit.qualifies)
        self.assertEqual(permit.classification, 'OTHER')
        self.assertEqual(permit.score, 0)

    def test_bare_duplex_planning_lead_still_qualifies(self):
        permit = permit_from_feature({
            'attributes': {
                'RecordID': 'PLN26-00749',
                'RecordName': '920 N CLITHERO DR',
                'Status': 'Applications in Review',
                'AddToTrackerDate': 1787054400000,
                'RecordType': 'Project',
                'PropertyAddress': '920 N CLITHERO DR',
                'Description': 'Duplex',
            }
        })
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, 'MULTIFAMILY')


if __name__ == '__main__':
    unittest.main()
