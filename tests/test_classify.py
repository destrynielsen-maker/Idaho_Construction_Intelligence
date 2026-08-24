import unittest
from idaho_permits.classify import classify_permit
from idaho_permits.models import Permit

def p(project,typ='',stage='PERMITTED'):
 return Permit('ID','Test','1','08/21/2026',typ,'1 Main St','x','https://x',project_name=project,stage=stage)
class TestClassify(unittest.TestCase):
 def test_duplex(self):
  x=classify_permit(p('DUPLEX W/GARAGE','Duplex')); self.assertTrue(x.qualifies); self.assertEqual(x.classification,'MULTIFAMILY')
 def test_noise(self):
  x=classify_permit(p('MECHANICAL PERMIT','Single-Family')); self.assertFalse(x.qualifies)
 def test_commercial_shell(self):
  x=classify_permit(p('NEW COMMERCIAL SHELL BUILDING','Commercial')); self.assertTrue(x.qualifies); self.assertEqual(x.classification,'COMMERCIAL')
 def test_planning_conversion_is_not_new_construction(self):
  x=p('1208 W FORT ST','Planning - Project',stage='PLANNING')
  x.building_use='Conversion of triplex to duplex and minor exterior modifications'
  x=classify_permit(x)
  self.assertFalse(x.qualifies); self.assertEqual(x.classification,'OTHER'); self.assertEqual(x.score,0)
