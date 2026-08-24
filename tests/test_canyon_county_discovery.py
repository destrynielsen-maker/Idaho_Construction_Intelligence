import unittest
from idaho_permits.collectors.canyon_county import candidate_layers


class CanyonCountyDiscoveryTests(unittest.TestCase):
    def test_selects_permit_building_and_development_layers(self):
        folder = {
            'services': [
                {'name': 'DSD/PublicTracker', 'type': 'MapServer'},
                {'name': 'DSD/Zoning', 'type': 'MapServer'},
            ]
        }
        payloads = {
            'DSD/PublicTracker': {
                'layers': [
                    {'id': 0, 'name': 'Addresses'},
                    {'id': 3, 'name': 'Building Permit Locations'},
                    {'id': 4, 'name': 'Planning Development Cases'},
                ]
            },
            'DSD/Zoning': {'layers': [{'id': 0, 'name': 'Zoning'}]},
        }
        rows = candidate_layers(folder, payloads)
        self.assertEqual([(x['layer_id'], x['layer_name']) for x in rows], [
            (3, 'Building Permit Locations'),
            (4, 'Planning Development Cases'),
        ])

    def test_ignores_unrelated_service_layers(self):
        folder = {'services': [{'name': 'DSD/Zoning', 'type': 'MapServer'}]}
        payloads = {'DSD/Zoning': {'layers': [{'id': 0, 'name': 'Parcels'}]}}
        self.assertEqual(candidate_layers(folder, payloads), [])


if __name__ == '__main__':
    unittest.main()
