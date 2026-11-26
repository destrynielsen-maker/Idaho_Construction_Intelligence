import unittest
from idaho_permits.models import Permit
from idaho_permits.reporting import reporting_report

def one(source,jurisdiction,permit_id,date):
    return Permit('ID',jurisdiction,permit_id,date,'Building','Test address',source,'https://example.test')

class CompactSourceEvidenceTests(unittest.TestCase):
    def test_meridian_verified_data_fallback_advances_success_but_not_baseline(self):
        p=one('Meridian permit report','Meridian','M1','2026-11-22')
        source={'source':'Meridian','status':'degraded','latest_issued_date':'2026-11-22'}
        r=reporting_report([source],{'Meridian':[p]},[p],{p.key},{},'2026-11-26T18:59:23Z')['sources'][0]
        self.assertEqual((r['availability'],r['collection_outcome']),('partial','unknown'))
        self.assertTrue(r['verified_data_fallback'])
        self.assertEqual(r['last_success_at'],'2026-11-26T18:59:23Z')
        self.assertEqual(r['latest_authoritative_date'],'2026-11-22')
        self.assertIsNone(r['new_since_previous_success'])
        self.assertFalse(r['comparable_success_baseline'])

    def test_post_falls_retained_date_does_not_invent_observation_or_success(self):
        p=one('City of Post Falls Building Permits GIS','Post Falls','PF1','2026-11-03')
        retained=reporting_report([{'source':'Post Falls','status':'error'}],{},[p],{p.key},{},'2026-11-26T18:59:23Z')['sources'][0]
        self.assertEqual(retained['retained_latest_authoritative_date'],'2026-11-03')
        self.assertEqual(retained['retained_records'],1)
        self.assertIsNone(retained['last_success_at'])
        self.assertIsNone(retained['observed_records'])
        self.assertIsNone(retained['latest_authoritative_date'])
        self.assertIsNone(retained['source_age_days'])

    def test_successful_post_falls_with_stale_authoritative_source_date(self):
        p=one('City of Post Falls Building Permits GIS','Post Falls','PF1','2026-11-02')
        state={'source':'Post Falls','status':'ok','latest_issued_date':'2026-11-03'}
        r=reporting_report([state],{'Post Falls':[p]},[p],{p.key},{},'2026-11-26T18:59:23Z')['sources'][0]
        self.assertEqual(r['latest_authoritative_date'],'2026-11-03')
        self.assertEqual(r['retained_latest_authoritative_date'],'2026-11-02')
        self.assertEqual(r['freshness_status'],'stale')
        self.assertEqual(r['collection_outcome'],'success')
