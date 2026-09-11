import unittest

from idaho_permits.classify import classify_permit
from idaho_permits.collectors.coeur_dalene import parse


class TestCDA(unittest.TestCase):
    def test_duplex_primary_building_is_extracted_and_child_trades_are_deduped(self):
        text = '''
Permit Num:
Owner:
Address: 412 W LINDEN AVE Project: DUPLEX W/GARAGE
Issued: Valuation: Type:
152695-B
Duplex08/17/2026Nicda Llc $450,000.00
Contractor: ARCHITERRA HOMES LLC
Permit Num:
Owner:
Address: 412 W LINDEN AVE Project: DUPLEX W/GARAGE
Issued: Valuation: Type:
152695-M1
Duplex08/17/2026Nicda Llc $0.00
Mechanical: ALPINA MECHANICAL LLC
'''
        rows = parse(text, 'https://x')
        self.assertEqual(len(rows), 1)
        permit = rows[0]
        self.assertEqual(permit.permit_number, '152695-B')
        self.assertEqual(permit.issued_date, '2026-08-17')
        self.assertEqual(permit.valuation, 450000)
        self.assertEqual(permit.contractor, 'ARCHITERRA HOMES LLC')
        self.assertEqual(permit.owner, 'Nicda Llc')
        self.assertEqual(permit.building_use, 'Duplex')
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, 'MULTIFAMILY')

    def test_townhouse_building_promotes_to_multifamily(self):
        text = '''
Permit Num:
Owner:
Address: 2715 N 14TH PL Project: Townhouse Building B
Issued: Valuation: Type:
152272-B
Town House08/07/20262707 N 15th St CDA LLC $667,646.48
Contractor: DAUM CONSTRUCTION
'''
        permit = parse(text, 'https://x')[0]
        self.assertEqual(permit.permit_type, 'New Multifamily Townhouse')
        classify_permit(permit)
        self.assertTrue(permit.qualifies)
        self.assertEqual(permit.classification, 'MULTIFAMILY')

    def test_adu_remodel_and_accessory_deck_are_not_promoted(self):
        text = '''
Permit Num:
Owner:
Address: 1029 N 2ND ST Project: ADU
Issued: Valuation: Type:
152105-B
Single-Family08/31/2026ANDREA MARIE QUEEN LIVING TRUST $55,000.00
Contractor: HOMEOWNER
Permit Num:
Owner:
Address: 701 E COEUR D' ALENE AVE Project: REMODEL SFD
Issued: Valuation: Type:
150927-B
Single-Family09/03/2026Jane Doe $200,000.00
Contractor: VISION BUILT CONSTRUCTION
Permit Num:
Owner:
Address: 1104 E STINER AVE Project: NEW 16'X16' DECK
Issued: Valuation: Type:
152715-B
Single-Family08/06/2026Connor Gullotto $17,000.00
Contractor: Evolutionary Builders LLC
'''
        rows = parse(text, 'https://x')
        self.assertEqual(len(rows), 3)
        by_number = {row.permit_number: row for row in rows}
        self.assertEqual(by_number['152715-B'].permit_type, 'Accessory Structure')
        self.assertIsNone(by_number['152715-B'].building_use)
        for permit in rows:
            classify_permit(permit)
            self.assertFalse(permit.qualifies)


if __name__ == '__main__':
    unittest.main()
