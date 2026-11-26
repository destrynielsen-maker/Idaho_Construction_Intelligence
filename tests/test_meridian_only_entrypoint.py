from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import os
import runpy
import unittest
from unittest.mock import patch

from idaho_permits import pipeline
from idaho_permits.collectors.base import CollectorResult
from idaho_permits.models import Permit
from idaho_permits.storage import load_permits, save_permits


class MeridianFixture:
    name = 'Meridian'
    def collect(self):
        rows=[Permit('ID','Meridian','EX-1','2026-11-18','New Single Family','Fixture address',
                     'Fixture report','https://example.invalid',contractor='EXAMPLE CONTRACTOR LLC')]
        return CollectorResult('Meridian','https://example.invalid',rows,
                               status='stale',latest_issued_date='2026-11-18',report_period_end='2026-11-22')


class TestMeridianEntryPoint(unittest.TestCase):
    def test_preserves_prior_markets_and_replays_meridian_without_duplicates(self):
        old=Permit('ID','Eagle','EX-2','2026-11-18','New Single Family','Fixture address',
                   'Fixture report','https://example.invalid',first_seen_at='2026-11-19',raw={'listing':True})
        with TemporaryDirectory() as tmp, patch.object(pipeline,'COLLECTORS',[MeridianFixture()]):
            store=Path(tmp)/'data'/'permits.json'; save_permits(store,[old],'2026-11-19')
            cwd=os.getcwd()
            try:
                os.chdir(tmp)
                first_seen=None
                for _ in range(2):
                    out=io.StringIO()
                    with redirect_stdout(out): runpy.run_module('idaho_permits.main',run_name='__main__')
                    status,=json.loads(out.getvalue())['sources']
                    self.assertEqual((status['status'],status['records_seen'],status['latest_issued_date']),
                                     ('stale',1,'2026-11-18'))
                    stored=load_permits(store)
                    self.assertEqual(set(stored),{old.key,'ID:MERIDIAN:EX-1'})
                    self.assertEqual(stored[old.key].first_seen_at,'2026-11-19')
                    self.assertTrue(stored[old.key].qualifies)  # Split does not change Eagle policy.
                    candidate=stored['ID:MERIDIAN:EX-1'].first_seen_at
                    self.assertEqual(candidate,first_seen or candidate)
                    first_seen=candidate
            finally:
                os.chdir(cwd)
