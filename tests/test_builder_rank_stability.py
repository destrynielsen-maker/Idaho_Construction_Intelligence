import json
import tempfile
import unittest
from pathlib import Path
from idaho_permits.dashboard import write_public_data
from idaho_permits.models import Permit

class BuilderRankStability(unittest.TestCase):
    def test_prior_tie_order_and_new_tie(self):
        def p(name,number):
            x=Permit('ID','Fixture',number,'2026-11-20','New single family dwelling','Example','Fixture','https://example.test')
            x.contractor=name; x.qualifies=True; x.score=20; x.valuation=100
            return x
        a,b,c=p('A','1'),p('B','2'),p('C','3')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def names():
                return [x['contractor'] for x in json.loads((root/'data/builders.json').read_text())]
            write_public_data(root,[a,b],[],'fixture')
            self.assertEqual(names(),['A','B'])
            write_public_data(root,[c,b,a],[],'fixture')
            self.assertEqual(names(),['A','B','C'])
            write_public_data(root,[b,a,c],[],'fixture')
            self.assertEqual(names(),['A','B','C'])
