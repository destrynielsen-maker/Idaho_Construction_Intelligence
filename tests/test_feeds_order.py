import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from idaho_permits.feeds import _ordered, _write
from idaho_permits.models import Permit


def row(number, date, score):
    p = Permit('ID','Test',number,date,'New single family dwelling','1 Main','x','https://x')
    p.qualifies = True
    p.classification = 'SINGLE_FAMILY'
    p.score = score
    return p


class FeedOrderingTests(unittest.TestCase):
    def test_standard_feeds_are_newest_first(self):
        old_high = row('OLD','2022-12-01',50)
        new_low = row('NEW','2026-08-20',15)
        self.assertEqual([p.permit_number for p in _ordered([old_high,new_low])], ['NEW','OLD'])

    def test_top_opportunities_remain_score_first(self):
        old_high = row('OLD','2022-12-01',50)
        new_low = row('NEW','2026-08-20',40)
        self.assertEqual([p.permit_number for p in _ordered([new_low,old_high], score_first=True)], ['OLD','NEW'])

    def test_serialized_rss_preserves_newest_first_order(self):
        old_high = row('OLD','2022-12-01',50)
        new_low = row('NEW','2026-08-20',15)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'feed.xml'
            _write(path, 'Test Feed', [old_high, new_low], 'https://example.com/')
            root = ET.parse(path).getroot()
            titles = [item.findtext('title') or '' for item in root.findall('./channel/item')]
        self.assertEqual(len(titles), 2)
        self.assertIn('NEW', titles[0])
        self.assertIn('OLD', titles[1])


if __name__ == '__main__':
    unittest.main()
