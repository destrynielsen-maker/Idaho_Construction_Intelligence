import unittest
from datetime import date

from idaho_permits.classify import classify_permit
from idaho_permits.collectors.post_falls import permit_from_attributes


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


if __name__ == '__main__':
    unittest.main()
