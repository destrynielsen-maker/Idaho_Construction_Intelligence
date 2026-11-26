import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from idaho_permits.collectors.base import CollectorResult
from idaho_permits.models import Permit
from idaho_permits.pipeline import run
from idaho_permits.reporting import reporting_report

def permit(num, day, source='Eagle iWorQ Permit Portal', jur='Eagle', **raw):
    return Permit('ID',jur,num,day,'Building Residential','123 Fictional Way',source,'https://example.test',building_use='Single Family Dwelling',raw=raw)

class Collector:
    name='Eagle'
    def __init__(self, permits=(), failing=False):
        self.permits=list(permits); self.failing=failing
    def collect(self):
        if self.failing: raise RuntimeError('synthetic unavailable')
        return CollectorResult(self.name,'https://example.test',self.permits)

class ReportingTests(unittest.TestCase):
    def test_boise_separate_and_no_fictitious_date(self):
        date='2026-11-26T17:00:00Z'
        plan=permit('P1','2026-11-22','Boise Development Tracker','Boise')
        legacy=permit('E1','2026-11-20')
        issued=permit('I1','2026-11-19','City of Boise Accela Citizen Access','Boise',source_issue_date_authoritative=True)
        future=permit('F1','2026-12-01','City of Boise Accela Citizen Access','Boise',source_issue_date_authoritative=True)
        canyon=permit('C1','2026-11-25','Canyon County DSD Building Permit Tracker','Canyon County')
        obs={'Boise':[plan],'Boise Issued Building Permits':[issued,future],'Eagle':[legacy],'Canyon County':[canyon]}
        out=reporting_report([dict(source=k,status='ok') for k in obs],obs,[plan,legacy,issued,future,canyon],{plan.key}, {},date)
        indexed={r['id']:r for r in out['sources']}
        self.assertEqual(indexed['boise-issued']['latest_authoritative_date'],'2026-11-19')
        self.assertEqual(indexed['boise-planning']['new_since_previous_success'],0)
        self.assertIsNone(indexed['boise-planning']['latest_authoritative_date'])
        self.assertIsNone(indexed['eagle']['latest_authoritative_date'])
        self.assertEqual(indexed['canyon-county']['latest_date_kind'],'application')

    def test_pinned_eagle_stored_history_includes_observed(self):
        seed=Path(__file__).resolve().parents[1]/'data/permits.json'
        permits=[Permit.from_dict(row) for row in json.loads(seed.read_text())['permits']]
        observed=next(p for p in permits if p.source_name=='Eagle iWorQ Permit Portal')
        history={p.key for p in permits}
        r=reporting_report([dict(source='Eagle',status='ok')],{'Eagle':[observed,observed]},permits,history,{},'2026-11-26T18:59:23Z')['sources'][0]
        self.assertEqual(r['retained_records'],2815)
        self.assertEqual(r['observed_records'],1)
        self.assertEqual(r['new_since_previous_success'],0)

    def test_pipeline_recovery_no_loss_or_duplicate(self):
        a=permit('11111111','2026-11-21',issue_date_verified=True)
        b=permit('22222222','2026-11-22',issue_date_verified=True)
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            def collect(c):
                with patch('idaho_permits.pipeline.COLLECTORS',[c]):run(tmp)
                doc=json.loads((tmp/'public/data/sources.json').read_text())
                rows=json.loads((tmp/'data/permits.json').read_text())['permits']
                self.assertEqual(len(rows),len({p['key'] for p in rows}))
                return doc['reporting_v1']['sources'][0],rows
            r1,s1=collect(Collector([a,a])); self.assertEqual(r1['new_since_previous_success'],1)
            failure,s2=collect(Collector(failing=True)); self.assertEqual(s1,s2)
            self.assertEqual(failure['last_success_at'],r1['last_success_at'])
            self.assertEqual(failure['retained_records'],1)
            self.assertEqual(failure['latest_authoritative_date'],'2026-11-21')
            self.assertIsNone(failure['new_since_previous_success'])
            r3,s3=collect(Collector([a,b,b])); self.assertEqual(r3['new_since_previous_success'],1)
            self.assertEqual(r3['retained_records'],2)
            self.assertEqual(len(s3),2)
            self.assertEqual(next(p for p in s3 if p['key']==a.key)['first_seen_at'],s1[0]['first_seen_at'])
            r4,_=collect(Collector([a,b])); self.assertEqual(r4['new_since_previous_success'],0)
