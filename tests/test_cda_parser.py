import unittest
from idaho_permits.collectors.coeur_dalene import parse
S='''Permit Num:\nOwner:\nAddress: 412 W LINDEN AVE Project: DUPLEX W/GARAGE\nIssued: Valuation: Type:\n152695-B\nNicda Llc 08/17/2026 $450,000.00 Duplex\nContractor: ARCHITERRA HOMES\nPermit Num:\n'''
class TestCDA(unittest.TestCase):
 def test_parse(self):
  rows=parse(S,'https://x'); self.assertEqual(len(rows),1); self.assertEqual(rows[0].permit_number,'152695-B'); self.assertEqual(rows[0].valuation,450000); self.assertEqual(rows[0].contractor,'ARCHITERRA HOMES')
