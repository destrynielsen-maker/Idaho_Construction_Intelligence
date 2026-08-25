import unittest
from datetime import date
from idaho_permits.collectors.caldwell import candidate_report_urls

class CaldwellDiscoveryTests(unittest.TestCase):
    def test_builds_current_and_previous_month_report_urls(self):
        rows = candidate_report_urls(date(2026, 8, 24), months_back=4)
        self.assertEqual([r['label'] for r in rows], [
            'August 2026', 'July 2026', 'June 2026', 'May 2026'
        ])
        self.assertTrue(rows[1]['url'].endswith('/july-2026-building-report.pdf'))

    def test_rolls_back_across_year_boundary(self):
        rows = candidate_report_urls(date(2026, 1, 5), months_back=3)
        self.assertEqual([r['label'] for r in rows], [
            'January 2026', 'December 2025', 'November 2025'
        ])

if __name__ == '__main__':
    unittest.main()
