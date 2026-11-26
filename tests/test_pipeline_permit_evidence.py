"""Exercise the public-production module entrypoint with an isolated fixture store."""
import json
import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from idaho_permits.collectors.base import CollectorResult
from idaho_permits.models import Permit
from idaho_permits.storage import save_permits


class PermitEvidencePipelineTests(unittest.TestCase):
    def test_history_not_deleted_and_replay_does_not_duplicate(self):
        old_eagle=Permit('ID','Eagle','08/19/2026','Building Residential','12 Fictional Way','Example','legacy','https://example.test/eagle-old',building_use='New single family',raw={'listing':{'date':'08/19/2026'}})
        old_meridian=Permit('ID','Meridian','R-NEW-2026-4','2026-08-19','New Residential','10 Fictional Way','legacy','https://example.test/meridian-old',first_seen_at='2026-08-20T00:00:00+00:00')
        new_meridian=Permit('ID','Meridian','R-NEW-2026-4','2026-08-19','New Residential','10 Fictional Way','new','https://example.test/meridian-current',contractor='Fictional Building LLC',raw={'contractor_role':'City report Contractor field; GC unverified'})
        eagle=Permit('ID','Eagle','261234','2026-08-19','Building Residential','11 Fictional Way','new','https://example.test/eagle',building_use='New single family',raw={'listing':{},'issue_date_verified':True})
        collectors=[
            SimpleNamespace(name='Meridian',collect=lambda:CollectorResult('Meridian','https://example.test', [new_meridian],status='stale',latest_issued_date='2026-08-19',report_period_end='2026-08-21')),
            SimpleNamespace(name='Eagle',collect=lambda:CollectorResult('Eagle','https://example.test',[eagle])),
        ]
        with TemporaryDirectory() as folder:
            root=Path(folder)
            save_permits(root/'data'/'permits.json',[old_eagle,old_meridian],'old')
            original=Path.cwd()
            try:
                os.chdir(root)
                with patch('idaho_permits.pipeline.COLLECTORS',collectors), patch('builtins.print'):
                    runpy.run_module('idaho_permits.main',run_name='__main__')
                    runpy.run_module('idaho_permits.main',run_name='__main__')
            finally:
                os.chdir(original)
            stored=json.loads((root/'data'/'permits.json').read_text())['permits']
            published=json.loads((root/'public'/'data'/'permits.json').read_text())['permits']
            status=json.loads((root/'public'/'data'/'sources.json').read_text())['collector_status']
        self.assertEqual(len(stored),3)
        self.assertEqual(len({p['key'] for p in stored}),3)
        self.assertIn(old_eagle.key,{p['key'] for p in stored})
        self.assertNotIn(old_eagle.key,{p['key'] for p in published})
        self.assertIn(eagle.key,{p['key'] for p in published})
        self.assertEqual(next(p for p in stored if p['key']==old_meridian.key)['first_seen_at'],old_meridian.first_seen_at)
        self.assertEqual(status[0]['status'],'stale')
        self.assertEqual(status[0]['latest_issued_date'],'2026-08-19')
        self.assertEqual(status[0]['report_period_end'],'2026-08-21')
