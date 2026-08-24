import unittest
from idaho_permits.feeds import _ordered
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


if __name__ == '__main__':
    unittest.main()
