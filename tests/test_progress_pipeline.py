import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from xml.etree import ElementTree

from idaho_permits import pipeline
from idaho_permits.collectors.base import CollectorResult
from idaho_permits.models import Permit
from idaho_permits.storage import save_permits


class ProgressPipelineTest(TestCase):
    def test_failed_scoped_refresh_preserves_progress_and_existing_lead_guids(self):
        url = 'https://example.invalid/county-issue-source'
        collect = Mock(side_effect=[
            CollectorResult('Canyon County', url, [], status='degraded', progress_complete=True,
                report_period_end='2026-11-24', progress_coverage_end='2026-11-25',
                progress_source_name='Canyon County verified issue window', progress=[
                    dict(state='ID', issuer='Canyon County', permit_id='PROGRESS-001', record_kind='building_permit',
                         stage='issued', issue_date='2026-11-24', source_url=url)]),
            RuntimeError('County source unavailable'),
        ])
        source = SimpleNamespace(name='Canyon County', landing_url=url, collect=collect)
        now = [datetime(2026, 11, day, 2, tzinfo=timezone.utc) for day in (25, 26)]
        observed_at = now[0].replace(minute=3)
        with TemporaryDirectory() as directory, patch.object(pipeline, 'COLLECTORS', [source]), \
                patch.object(pipeline, 'datetime', wraps=datetime) as clock:
            clock.now.side_effect = [now[0], observed_at, now[1]]
            root = Path(directory)
            lead_store = root/'data'/'permits.json'
            progress_store = root/'data'/'permit-progress.json'
            public_progress = root/'public'/'data'/'permit-progress.json'
            public_feed = root/'public'/'feeds'/'new-construction.xml'
            prior = Permit('ID', 'Canyon County', 'LEGACY-001', '2026-11-20', 'New single-family building',
                           'Test project address', 'Fixture', url, first_seen_at='2026-11-21T02:00:00+00:00')
            save_permits(lead_store, [prior], now[0].isoformat())

            pipeline.run(root)
            baseline = progress_store.read_bytes()
            progress = json.loads(baseline)
            source_name = 'Canyon County verified issue window'
            self.assertEqual(progress['sources'][0]['source_name'], source_name)
            self.assertEqual(progress['permits'][0]['source_name'], source_name)
            self.assertEqual(progress['sources'][0]['last_successful_refresh'], observed_at.isoformat())
            self.assertEqual(progress['permits'][0]['last_observed_at'], observed_at.isoformat())
            self.assertEqual(progress['sources'][0]['latest_date_covered'], '2026-11-25')
            self.assertEqual(baseline, public_progress.read_bytes())
            before = json.loads(lead_store.read_text(encoding='utf-8'))['permits']
            guids = [element.text for element in ElementTree.parse(public_feed).findall('./channel/item/guid')]
            self.assertEqual(guids, [prior.key])
            self.assertEqual([p['key'] for p in before], [prior.key])
            self.assertEqual(before[0]['first_seen_at'], prior.first_seen_at)

            result = pipeline.run(root)
            self.assertEqual(result['sources'][0]['status'], 'error')
            self.assertEqual(progress_store.read_bytes(), baseline)
            self.assertEqual(public_progress.read_bytes(), baseline)
            self.assertEqual(json.loads(lead_store.read_text(encoding='utf-8'))['permits'], before)
            self.assertEqual([element.text for element in ElementTree.parse(public_feed).findall('./channel/item/guid')], guids)
