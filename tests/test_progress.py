import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from idaho_permits.progress import PermitProgress


URL = 'https://example.invalid/building'
FIRST = '2026-11-24T02:00:00+00:00'
SECOND = '2026-11-25T02:00:00+00:00'
THIRD = '2026-11-26T02:00:00+00:00'
FOURTH = '2026-11-27T02:00:00+00:00'
PERMIT_KEY = 'ID:CANYON COUNTY:PERMIT-001'
SOURCE_KEY = ('ID', 'CANYON COUNTY', 'Canyon County')


def record(**fields):
    return {'state': 'ID', 'issuer': 'Canyon County', 'permit_id': 'Permit-001', 'record_kind': 'building_permit',
            'stage': 'application_under_review', 'source_url': URL, 'received_date': '2026-11-21', **fields}


class PermitProgressTest(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.canonical = root/'data'/'permit-progress.json'
        self.public = root/'public'/'data'/'permit-progress.json'
        self.ledger = PermitProgress.load(self.canonical)

    def observe(self, records, stamp, *, complete=True, coverage_end=None):
        self.ledger.observe('Canyon County', URL, records, stamp, complete=complete, coverage_end=coverage_end,
                            default_issuer=('ID', 'Canyon County'))

    def test_two_snapshots_distinguish_observation_and_authoritative_issue_date(self):
        self.observe([record(private_raw='not exported')], FIRST)
        self.assertEqual(self.ledger.permits[PERMIT_KEY]['changes'], [])
        self.ledger.save(self.canonical, self.public)
        self.ledger = PermitProgress.load(self.canonical)
        issued = record(stage='issued', issue_date='2026-11-23', issued_flag=True, source_status='Issued')
        self.observe([issued], SECOND, coverage_end='2026-11-25')
        before = self.ledger.permits[PERMIT_KEY]
        transitions = [x for x in before['changes'] if x['field'] == 'stage']
        self.assertEqual(transitions, [dict(field='stage', previous_value='application_under_review', new_value='issued',
                                            observed_at=SECOND, event_date='2026-11-23')])
        status_change, = [item for item in before['changes'] if item['field'] == 'source_status']
        self.assertIsNone(status_change['event_date'])
        self.observe([issued], THIRD)
        self.assertEqual(self.ledger.permits[PERMIT_KEY]['changes'], before['changes'])
        self.assertEqual(self.ledger.permits[PERMIT_KEY]['last_observed_at'], THIRD)
        self.assertEqual(self.ledger.sources[SOURCE_KEY]['latest_date_covered'], '2026-11-25')
        self.ledger.save(self.canonical, self.public)
        self.assertEqual(self.canonical.read_bytes(), self.public.read_bytes())
        self.assertNotIn('private_raw', self.public.read_text(encoding='utf-8'))

    def test_rolling_absence_partial_batches_and_failed_refresh_preserve_history(self):
        self.observe([record()], FIRST)
        self.observe([record(permit_id='Permit-002', review_date='2026-11-25')], SECOND, complete=False,
                     coverage_end='2026-11-26')
        self.assertEqual(self.ledger.permits[PERMIT_KEY]['last_observed_at'], FIRST)
        self.assertEqual(self.ledger.sources[SOURCE_KEY]['last_successful_refresh'], FIRST)
        self.assertEqual(self.ledger.sources[SOURCE_KEY]['latest_date_covered'], '2026-11-21')
        self.ledger.save(self.canonical, self.public)
        before = self.canonical.read_bytes()
        bad = [record(stage='issued'), record(issue_date='2026-11-27', permit_id='Permit-003')]
        with self.assertRaises(ValueError):
            self.observe(bad, THIRD)
        self.ledger.save(self.canonical, self.public)
        self.assertEqual(self.canonical.read_bytes(), before)

    def test_weaker_snapshot_cannot_downgrade_issued_or_closed_stage(self):
        self.observe([record(stage='issued', issue_date='2026-11-22', source_status='Issued', issued_flag=True,
                             inspection_status='Passed')], FIRST)
        self.observe([record(stage='review_approved_no_issue', review_date='2026-11-25',
                             source_status='Review approved', inspection_status='unknown')], SECOND)
        permit = self.ledger.permits[PERMIT_KEY]
        self.assertEqual((permit['stage'], permit['issue_date'], permit['review_date']),
                         ('issued', '2026-11-22', '2026-11-25'))
        self.assertEqual([change['field'] for change in permit['changes']], ['review_date', 'source_status'])
        self.assertEqual(permit['inspection_status'], 'Passed')
        self.assertIsNone(permit['changes'][-1]['event_date'])
        self.observe([record(stage='closed', source_status='Closed')], THIRD)
        self.observe([record(stage='issued', source_status='Issued', closed_date='2026-11-26')], FOURTH)
        permit = self.ledger.permits[PERMIT_KEY]
        self.assertEqual(permit['stage'], 'closed')
        stage_change = [change for change in permit['changes'] if change['field'] == 'stage'][0]
        self.assertIsNone(stage_change['event_date'])
        self.assertEqual(permit['closed_date'], '2026-11-26')

    def test_planning_and_building_collection_sources_do_not_conflate(self):
        plan = record(issuer='Boise', permit_id='PLAN-001', record_kind='planning', stage='planning')
        self.ledger.observe('Boise', URL, [plan], FIRST, complete=True)
        self.ledger.observe('Boise Issued Building Permits', URL, [], SECOND, complete=True,
                            coverage_end='2026-11-25', default_issuer=('ID', 'Boise'))
        self.assertEqual(len(self.ledger.sources), 2)
        self.assertEqual(self.ledger.permits['ID:BOISE:PLAN-001']['stage'], 'planning')
        with self.assertRaisesRegex(ValueError, 'planning record and a building permit'):
            self.ledger.observe('Boise Issued Building Permits', URL,
                                [record(issuer='Boise', permit_id='PLAN-001')], THIRD)

    def test_explicit_disposition_updates_current_stage_and_keeps_issue_history(self):
        self.observe([record(stage='issued', issue_date='2026-11-22', issued_flag=True,
                             source_disposition='active')], FIRST)
        self.observe([record(stage='unknown', source_disposition='withdrawn', source_status='Withdrawn')], SECOND)
        withdrawn = self.ledger.permits[PERMIT_KEY]
        self.assertEqual((withdrawn['stage'], withdrawn['issue_date']), ('unknown', '2026-11-22'))
        self.observe([record(stage='closed', source_disposition='closed', closed_date='2026-11-26')], THIRD)
        self.observe([record(source_disposition='active', source_status='Active / In Progress')], FOURTH)
        reopened = self.ledger.permits[PERMIT_KEY]
        self.assertEqual((reopened['stage'], reopened['issue_date'], reopened['closed_date']),
                         ('issued', '2026-11-22', '2026-11-26'))
        change = [item for item in reopened['changes'] if item['field'] == 'stage'][-1]
        self.assertEqual((change['previous_value'], change['new_value'], change['event_date']), ('closed', 'issued', None))

    def test_status_and_coverage_links_continue_to_support_their_evidence(self):
        newer_url = 'https://example.invalid/newer-report'
        older_url = 'https://example.invalid/older-report'
        self.ledger.observe('Canyon County', newer_url, [record(source_status='Approved', review_result='Approved',
                            review_date='2026-11-22')], FIRST, complete=True, coverage_end='2026-11-24')
        older = record(review_result='In Progress', source_url=older_url)
        self.ledger.observe('Canyon County', older_url, [older], SECOND, complete=True, coverage_end='2026-11-23')
        permit = self.ledger.permits[PERMIT_KEY]
        self.assertEqual((permit['source_url'], permit['source_status_url']), (older_url, URL))
        self.assertEqual((permit['review_result'], permit['review_date']), ('In Progress', None))
        source = self.ledger.sources[SOURCE_KEY]
        self.assertEqual((source['source_url'], source['latest_date_covered']), (newer_url, '2026-11-24'))

    def test_first_unobserved_publish_exports_empty_without_new_history_file(self):
        self.ledger.save(self.canonical, self.public)
        self.assertFalse(self.canonical.exists())
        self.assertEqual(json.loads(self.public.read_text(encoding='utf-8')), {'sources': [], 'permits': []})
