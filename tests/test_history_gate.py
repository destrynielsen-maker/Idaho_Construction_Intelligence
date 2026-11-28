import copy
import hashlib
import math
import json
import shutil
from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from idaho_permits import pipeline
from idaho_permits.collectors.base import CollectorResult
from idaho_permits.models import Permit
from idaho_permits.reporting import SOURCES
from idaho_permits.storage import load_permits

WORKTREE = Path(__file__).resolve().parents[1]
FROZEN = WORKTREE / 'data/permits.json'

def keyed(rows):
    result = {p['key']: p for p in rows}
    if len(result) != len(rows):
        raise AssertionError('Duplicate permit identity')
    return result

def read_docs(path):
    return json.loads(path.read_text())

def signature(work):
    ledger = keyed(read_docs(work/'data/permits.json')['permits'])
    leads = keyed(read_docs(work/'public/data/permits.json')['permits'])
    feeds = {p.name:[n.text for n in ET.parse(p).findall('./channel/item/guid')]
             for p in sorted((work/'public/feeds').glob('*.xml'))}
    builders = read_docs(work/'public/data/builders.json')
    return ledger, leads, feeds, builders

class ReplayCollector:
    def __init__(self, original, rows, attempts, omitted, failed):
        self.__dict__.update(name=original.name, replace_jurisdiction=getattr(original,'replace_jurisdiction',False),
                             rows=rows, attempts=attempts, omitted=omitted, failed=failed)
    def collect(self):
        self.attempts.append(self.name)
        if self.name in self.failed:
            raise TimeoutError('Fixture: no source response')
        by_name=SOURCES[self.name][3]
        rr=[copy.deepcopy(p) for p in self.rows.values() if p.source_name in by_name and p.key not in self.omitted]
        return CollectorResult(self.name, 'https://example.test/fixture', rr)

class HistoryGateTest(unittest.TestCase):
    def setUp(self):
        self.seed=load_permits(FROZEN)
        self.originals=pipeline.COLLECTORS
        self.seed_digest=hashlib.sha256(FROZEN.read_bytes()).hexdigest()

    def replay(self, work, omitted=(), failed=()):
        (work/'data').mkdir(parents=True)
        (work/'data/permits.json').write_bytes(FROZEN.read_bytes())
        # Reproduce the real refresh against the exact served feed order.
        shutil.copytree(WORKTREE/'public/feeds',work/'public/feeds')
        (work/'public/data').mkdir(parents=True)
        shutil.copy2(WORKTREE/'public/data/builders.json',work/'public/data/builders.json')
        attempts=[]
        collectors=[ReplayCollector(c,self.seed,attempts,omitted,failed) for c in self.originals]
        with patch.object(pipeline,'COLLECTORS',collectors):
            out=pipeline.run(work)
        self.assertEqual(attempts,[c.name for c in self.originals])
        self.assertEqual(len(attempts),10)
        self.assertEqual(hashlib.sha256(FROZEN.read_bytes()).hexdigest(),self.seed_digest)
        return out

    def test_frozen_ledger_survives_both_omissions_and_source_errors(self):
        post=sorted((p for p in self.seed.values() if p.jurisdiction=='Post Falls'),key=lambda p:p.issued_date)
        county=[p for p in self.seed.values() if p.jurisdiction=='Canyon County' and p.qualifies]
        self.assertTrue(len(post)>12 and len(county)>0)
        omitted={p.key for p in post[:12]+county[:3]}
        failed={'Eagle','Nampa'}
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/'full',Path(d)/'omission'
            self.replay(a,failed=failed)
            outcome=self.replay(b,omitted=omitted,failed=failed)
            full,full_leads,full_feeds,full_builders=signature(a)
            output,leads,feeds,builders=signature(b)
            _,prior_leads,prior_feeds,prior_builders=signature(WORKTREE)
            expected_public={p.key for p in self.seed.values() if p.qualifies}
            self.assertEqual(set(output),set(self.seed))
            self.assertEqual(set(leads),expected_public)
            self.assertEqual(set(leads),set(full_leads))
            self.assertEqual(set(leads),set(prior_leads))
            self.assertEqual(len(full_feeds),5)
            self.assertEqual(feeds,full_feeds)
            self.assertEqual(feeds,prior_feeds)
            self.assertEqual(builders,full_builders)
            self.assertEqual([b['contractor'] for b in builders],[b['contractor'] for b in prior_builders])
            for actual,prior in zip(builders,prior_builders):
                self.assertEqual(actual['count'],prior['count'])
                self.assertEqual(actual['score_total'],prior['score_total'])
                self.assertTrue(math.isclose(actual['valuation_total'],prior['valuation_total'],abs_tol=0.005,rel_tol=0),
                                'Builder valuation changed beyond half-cent: '+actual['contractor'])
            for key, prior in self.seed.items():
                row=output[key]
                self.assertEqual(row['first_seen_at'],prior.first_seen_at)
                self.assertEqual((row['qualifies'],row['score'],row['sales_score']),
                                 (prior.qualifies,prior.score,prior.sales_score))
                if key in omitted:
                    self.assertEqual(row,prior.to_dict())
            latest={x['source']:x for x in outcome['sources']}
            self.assertEqual(latest['Post Falls']['retained_not_observed_in_latest_pull'],12)
            self.assertEqual(latest['Canyon County']['retained_not_observed_in_latest_pull'],3)
            report=read_docs(b/'public/data/sources.json')['reporting_v1']
            by_id={row['id']: row for row in report['sources']}
            self.assertEqual(by_id['post-falls']['retained_records']-by_id['post-falls']['observed_records'],12)
            self.assertEqual(by_id['canyon-county']['retained_records']-by_id['canyon-county']['observed_records'],3)
            for target in ('nampa','eagle'):
                self.assertIsNone(by_id[target]['observed_records'])
                self.assertEqual(by_id[target]['collection_outcome'],'error')
            print('10-source frozen replay:',len(output),'retained;',len(leads),'published;',len(omitted),'omitted preserved;',
                   {k:len(v) for k,v in feeds.items()},'source hashes SHA-256',self.seed_digest)

    def test_duplicate_ledger_fails_before_any_generated_write(self):
        p=next(iter(self.seed.values())).to_dict()
        with tempfile.TemporaryDirectory() as d:
            work=Path(d)
            store=work/'data/permits.json'; store.parent.mkdir()
            original=json.dumps({'permits':[p,p]}).encode()
            store.write_bytes(original)
            with self.assertRaisesRegex(ValueError,'Duplicate historical permit identity'):
                pipeline.run(work)
            self.assertEqual(store.read_bytes(),original)
            self.assertFalse((work/'public').exists())

    def test_fail_closed_when_prior_key_or_first_seen_changes(self):
        p=copy.deepcopy(next(iter(self.seed.values())))
        with self.assertRaisesRegex(RuntimeError,'1 missing IDs, 0 altered'):
            pipeline._verify_history({p.key:p.first_seen_at},{})
        prior=p.first_seen_at
        p.first_seen_at='1900-01-01T12:00:00Z'
        with self.assertRaisesRegex(RuntimeError,'0 missing IDs, 1 altered'):
            pipeline._verify_history({p.key:prior},{p.key:p})

    def test_mutation_gate_leaves_existing_generated_files_untouched(self):
        p=next(iter(self.seed.values())).to_dict()
        with tempfile.TemporaryDirectory() as d:
            work=Path(d)
            store=work/'data/permits.json'; store.parent.mkdir()
            original=json.dumps({'permits':[p]}).encode(); store.write_bytes(original)
            previous=work/'public/data/permits.json'; previous.parent.mkdir(parents=True)
            previous.write_bytes(b'prior public artifact')
            def corrupt(row):
                row.first_seen_at='1900-01-01T12:00:00Z'
            with patch.object(pipeline,'COLLECTORS',[]), patch.object(pipeline,'classify_permit',corrupt):
                with self.assertRaisesRegex(RuntimeError,'0 missing IDs, 1 altered'):
                    pipeline.run(work)
            self.assertEqual(store.read_bytes(),original)
            self.assertEqual(previous.read_bytes(),b'prior public artifact')

    def test_new_keys_added_but_null_first_seen_not_rewritten(self):
        original=copy.deepcopy(next(p for p in self.seed.values() if p.jurisdiction=='Post Falls'))
        original.first_seen_at=None
        new=copy.deepcopy(original); new.permit_number='BLDR-26-999994'
        from unittest.mock import Mock
        source=Mock(name='fixture'); source.name='Post Falls'; source.replace_jurisdiction=True
        source.collect.return_value=CollectorResult('Post Falls','https://example.test',[original,new,new])
        with tempfile.TemporaryDirectory() as d:
            work=Path(d); ledger_path=work/'data/permits.json'; ledger_path.parent.mkdir()
            ledger_path.write_text(json.dumps({'permits':[original.to_dict()]}))
            with patch.object(pipeline,'COLLECTORS',[source]): pipeline.run(work)
            after=load_permits(ledger_path)
            self.assertEqual(set(after),{original.key,new.key})
            self.assertIsNone(after[original.key].first_seen_at)
            self.assertIsNotNone(after[new.key].first_seen_at)
