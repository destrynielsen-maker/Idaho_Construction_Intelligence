import unittest
from idaho_permits.classify import classify_permit
from idaho_permits.models import Permit

def p(project,typ=''):
 return Permit('ID','Test','1','08/21/2026',typ,'1 Main St','x','https://x',project_name=project)
class TestClassify(unittest.TestCase):
 def test_duplex(self):
  x=classify_permit(p('DUPLEX W/GARAGE','Duplex')); self.assertTrue(x.qualifies); self.assertEqual(x.classification,'MULTIFAMILY')
 def test_noise(self):
  x=classify_permit(p('MECHANICAL PERMIT','Single-Family')); self.assertFalse(x.qualifies)
 def test_commercial_shell(self):
  x=classify_permit(p('NEW COMMERCIAL SHELL BUILDING','Commercial')); self.assertTrue(x.qualifies); self.assertEqual(x.classification,'COMMERCIAL')
