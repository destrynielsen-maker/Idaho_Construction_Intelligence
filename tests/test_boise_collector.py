import unittest
from datetime import date

from idaho_permits.classify import classify_permit
from idaho_permits.collectors.boise import BoiseIssuedPermitCollector, permit_from_feature


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

    def setUp(self):
        self.collector = BoiseIssuedPermitCollector()
        self.today = date(2026, 8, 25)
        self.cutoff = date(2026, 7, 11)

    def row(self, description, project='Test Project', number='BLD26-02000'):
        return {
            'application_date': '2026-07-01',
            'permit_number': number,
            'status': 'Issued',
            'description': description,
            'project_name': project,
            'address': '100 W MAIN ST, Boise ID 83702',
            'source_url': 'https://permits.cityofboise.org/CitizenAccess/Cap/CapDetail.aspx?Module=Building&id=1',
        }

    def detail(self, **overrides):
        data = {
            'status': 'Issued',
            'issued_date': '2026-08-20',
            'received_date': '2026-03-01',
            'application_code': 402,
            'type_of_permit': 'New Structure',
            'type_of_use': 'Single Family Dwelling',
            'type_of_work': 'New',
            'detached_adu': 'No',
            'units': None,
            'existing_building_area': 0.0,
            'new_building_area': 2200.0,
            'total_building_area': 2200.0,
            'valuation': 525000.0,
            'contractor': 'TEST HOMES LLC',
        }
        data.update(overrides)
        return data

    def test_issued_sfr_maps_and_qualifies(self):
        row = self.row('Permit for the construction of a new 2,200 sq ft single family dwelling.')
        permit = self.collector._permit(row, self.detail(), 'residential', {402, 403, 404}, self.cutoff, self.today)
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, 'SINGLE_FAMILY')
        self.assertEqual(permit.issued_date, '2026-08-20')
        self.assertEqual(permit.valuation, 525000.0)
        self.assertEqual(permit.contractor, 'TEST HOMES LLC')

    def test_residential_adu_is_rejected(self):
        row = self.row('Permit for the construction of a new detached ADU.')
        detail = self.detail(detached_adu='Yes')
        self.assertFalse(self.collector._row_scope_candidate('residential', row))
        self.assertIsNone(self.collector._permit(row, detail, 'residential', {402, 403, 404}, self.cutoff, self.today))

    def test_townhouse_is_promoted_to_multifamily_classifier(self):
        row = self.row('Permit for the construction of a new three-story townhouse.')
        permit = self.collector._permit(row, self.detail(), 'residential', {402, 403, 404}, self.cutoff, self.today)
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, 'MULTIFAMILY')

    def test_commercial_ground_up_maps_and_qualifies(self):
        row = self.row('Permit for construction of a new 27,512 sf industrial fabrication building.')
        detail = self.detail(
            application_code=502,
            type_of_permit=None,
            type_of_use='Industrial',
            type_of_work=None,
            new_building_area=27512.0,
            total_building_area=27512.0,
            valuation=4200000.0,
        )
        permit = self.collector._permit(row, detail, 'commercial', {502}, self.cutoff, self.today)
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, 'COMMERCIAL')

    def test_commercial_addition_or_remodel_is_rejected(self):
        addition = self.row('Micron B50 4,620 sf addition to the existing fabrication building.')
        remodel = self.row('Remodel existing office and warehouse with interior alterations.')
        detail = self.detail(application_code=502, type_of_permit=None, type_of_use='Commercial', type_of_work=None)
        self.assertFalse(self.collector._row_scope_candidate('commercial', addition))
        self.assertFalse(self.collector._row_scope_candidate('commercial', remodel))
        self.assertIsNone(self.collector._permit(addition, detail, 'commercial', {502}, self.cutoff, self.today))
        self.assertIsNone(self.collector._permit(remodel, detail, 'commercial', {502}, self.cutoff, self.today))

    def test_foundation_only_commercial_is_rejected(self):
        row = self.row('Foundation only for new pumphouse. NO VERTICAL CONSTRUCTION IS ALLOWED.')
        detail = self.detail(application_code=502, type_of_permit=None, type_of_use='Commercial', type_of_work=None)
        self.assertFalse(self.collector._row_scope_candidate('commercial', row))
        self.assertIsNone(self.collector._permit(row, detail, 'commercial', {502}, self.cutoff, self.today))

    def test_multifamily_new_building_maps_units_and_qualifies(self):
        row = self.row('Permit for the construction of a new 5,745 sq ft, 4-unit two-story building.', project='Dorothy Fourplex')
        detail = self.detail(
            application_code=506,
            type_of_permit=None,
            type_of_use='Multifamily',
            type_of_work=None,
            units=4,
            new_building_area=5745.0,
            total_building_area=5745.0,
            valuation=475000.0,
        )
        permit = self.collector._permit(row, detail, 'multifamily', {506}, self.cutoff, self.today)
        self.assertIsNotNone(permit)
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, 'MULTIFAMILY')
        self.assertEqual(permit.units, 4)

    def test_multifamily_carport_is_rejected(self):
        row = self.row('Add carports to existing apartment parking area.', project='Apartment Carports')
        detail = self.detail(application_code=506, type_of_use='Multifamily', units=11)
        self.assertFalse(self.collector._row_scope_candidate('multifamily', row))
        self.assertIsNone(self.collector._permit(row, detail, 'multifamily', {506}, self.cutoff, self.today))

    def test_old_or_future_issue_date_is_rejected(self):
        row = self.row('Permit for construction of a new single family dwelling.')
        self.assertIsNone(self.collector._permit(row, self.detail(issued_date='2026-07-01'), 'residential', {402, 403, 404}, self.cutoff, self.today))
        self.assertIsNone(self.collector._permit(row, self.detail(issued_date='2026-08-26'), 'residential', {402, 403, 404}, self.cutoff, self.today))

    def test_record_type_leak_fails_closed(self):
        row = self.row('Permit for construction of a new single family dwelling.')
        with self.assertRaises(RuntimeError):
            self.collector._permit(row, self.detail(application_code=501), 'residential', {402, 403, 404}, self.cutoff, self.today)

    def test_date_text_separates_received_from_issued_dates(self):
        self.assertEqual(self.collector._date_text('08/10/2026'), '2026-08-10')
        self.assertEqual(self.collector._date_text('03/05/2026'), '2026-03-05')
        self.assertEqual(self.collector._date_text('bad date'), '')


if __name__ == '__main__':
    unittest.main()
