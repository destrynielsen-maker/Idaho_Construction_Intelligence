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
    def test_application_only_source_reports_coverage_without_publishing_leads(self):
        url = 'https://example.invalid/county-building-applications'
        stamp = datetime(2026, 11, 28, 8, tzinfo=timezone.utc)
        batch = CollectorResult('Ada County', url, [], progress_complete=True, progress_coverage_end='2026-11-27',
            progress=[dict(state='ID', issuer='Ada County', permit_id='APP-001', record_kind='building_permit',
                           stage='application_under_review', received_date='2026-11-27', source_url=url)])
        unexpected_lead = Permit('ID', 'Ada County', 'UNAUTHORIZED-LEAD', '2026-11-27',
                                 'New single-family building', 'Fixture address', 'Fixture', url)
        invalid = CollectorResult('Ada County', url, [unexpected_lead], progress=batch.progress)
        issue = CollectorResult('Ada County', url, [], progress=[dict(batch.progress[0], issue_date='2026-11-27')])
        wrong_issuer = CollectorResult('Ada County', url, [], progress=[dict(batch.progress[0], issuer='Boise')])
        source = SimpleNamespace(name='Ada County', landing_url=url, progress_only=True,
                                 collect=Mock(side_effect=[batch, invalid, issue, wrong_issuer]))
        with TemporaryDirectory() as directory, patch.object(pipeline, 'COLLECTORS', [source]), \
                patch.object(pipeline, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = stamp
            root = Path(directory)
            data = root/'public'/'data'
            result = pipeline.run(root)
            status, = result['sources']
            self.assertEqual((status['records_seen'], status['qualifying_records']), (1, 0))
            self.assertEqual(result['total_stored'], 0)
            report = json.loads((data/'sources.json').read_text(encoding='utf-8'))['reporting_v1']['sources'][0]
            self.assertEqual((report['observed_records'], report['retained_records']), (1, 1))
            self.assertEqual((report['collection_outcome'], report['latest_date_kind']), ('success', 'application'))
            self.assertEqual(report['latest_authoritative_date'], '2026-11-27')
            before = (data/'permit-progress.json').read_bytes()
            self.assertEqual(json.loads(before)['permits'][0]['permit_id'], 'APP-001')
            for malformed in ('lead', 'issuance', 'issuer'):
                with self.subTest(malformed=malformed):
                    result = pipeline.run(root)
                    self.assertEqual(result['sources'][0]['status'], 'error')
                    self.assertEqual(result['total_stored'], 0)
                    self.assertEqual((data/'permit-progress.json').read_bytes(), before)
            feed = root/'public'/'feeds'/'new-construction.xml'
            self.assertEqual(ElementTree.parse(feed).findall('./channel/item/guid'), [])

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
