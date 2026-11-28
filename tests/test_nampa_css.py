import os
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from idaho_permits.collectors.base import CollectorResult
from idaho_permits.collectors.nampa_css import parse_batch, collect_css, SEARCH_TYPE, SITE
from idaho_permits.classify import classify_permit

LO,HI=date(2026,11,23),date(2026,11,27)

def fixture():
    return {'scope':SEARCH_TYPE,'period':{'lo':LO.isoformat(),'hi':HI.isoformat()},'count':1,
        'rows':[dict(id='RES-12345-2026',type=SEARCH_TYPE,status='Issued',
        url=SITE+'#/permit/11111111-1111-1111-1111-111111111111',issued='2026-11-24',
        address='1 TEST WAY',description='NEW SFD LT 11 BLK 2 TEST',contractor=None)]}

class NampaCSSTest(unittest.TestCase):
    def test_explicit_individual_scope(self):
        batch=parse_batch(fixture(),LO,HI)
        p,=batch.permits
        classify_permit(p)
        self.assertEqual((p.classification,p.valuation,p.contractor),('SINGLE_FAMILY',None,None))
        self.assertEqual((batch.status,batch.latest_issued_date),('degraded','2026-11-24'))
        self.assertTrue(batch.progress_complete)
        row, = batch.progress
        self.assertEqual((row['stage'], row['issue_date'], row['source_status'], row['inspection_status']),
                         ('issued', '2026-11-24', 'Issued', 'unknown'))
        self.assertTrue(row['issued_flag'])
        finaled = fixture()
        finaled['rows'][0]['status'] = 'Finaled'
        row, = parse_batch(finaled, LO, HI).progress
        self.assertEqual((row['stage'], row['source_status']), ('issued', 'Finaled'))
        self.assertIsNone(row['issued_flag'])
        self.assertNotIn('closed_date', row)

    def test_reject_wrong_date_scope_count_and_authority(self):
        for changing in (dict(issued='2026-11-28'),dict(status='Approved'),dict(description='NEW SFD FIRE DAMAGE RESTORATION'),
                         dict(url='https://other.invalid/#/permit/fake'),dict(contractor=[])):
            with self.subTest(changing=changing):
                f=fixture()
                f['rows'][0].update(changing)
                with self.assertRaises(ValueError): parse_batch(f,LO,HI)

        f=fixture()
        f['count']=2
        with self.assertRaises(ValueError): parse_batch(f,LO,HI)
        f['rows'].append(dict(f['rows'][0],id='RES-54321-2026'))
        with self.assertRaises(ValueError): parse_batch(f,LO,HI)

    def test_partial_details_keep_verified_subset_with_reconciled_counts(self):
        batch = fixture()
        batch.update(observedCount=2, detailUnavailable=1)
        result = parse_batch(batch, LO, HI)
        self.assertEqual(len(result.permits), 1)
        self.assertFalse(result.progress_complete)
        self.assertIn('Verified 1 of 2 search results', result.note)
        batch['observedCount'] = 3
        with self.assertRaises(ValueError):
            parse_batch(batch, LO, HI)

    def test_keep_pdf_if_fallback_unavailable(self):
        from idaho_permits.collectors.nampa import NampaPermitCollector

        historical=CollectorResult('Nampa','https://www.cityofnampa.us',[],'old',status='stale')
        with patch.dict(os.environ,{'NAMPA_CSS_FALLBACK':'1'}),patch.object(NampaPermitCollector,'_collect_pdf',return_value=historical),patch('idaho_permits.collectors.nampa_css.collect_css',side_effect=RuntimeError):
            self.assertIs(NampaPermitCollector().collect(),historical)

    def test_existing_path_untouched_without_opt_in(self):
        from idaho_permits.collectors.nampa import NampaPermitCollector

        ready=CollectorResult('Nampa','https://www.cityofnampa.us',[])
        with patch.dict(os.environ,{'NAMPA_CSS_FALLBACK':'0'}),patch.object(NampaPermitCollector,'_collect_pdf',return_value=ready),patch('idaho_permits.collectors.nampa_css.collect_css') as browser:
            self.assertIs(NampaPermitCollector().collect(),ready)
            browser.assert_not_called()

    def test_probe_is_bounded_no_shell(self):
        import json
        p=fixture(); p['period']['lo']='2026-11-21'
        with patch('idaho_permits.collectors.nampa_css.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(p).encode())) as browser:
            self.assertEqual(len(collect_css(HI).permits),1)
            args, opts=browser.call_args
            self.assertEqual(args[0][-3:],['11/21/2026','11/27/2026','--full'])
            self.assertNotIn('shell',opts)
