import copy
from datetime import date
import unittest

from idaho_permits.models import Permit
from idaho_permits.reporting import CANYON_TRACKER,canyon_utc_civil,canyon_issue_evidence,reporting_report

class CanyonIssuedReporting(unittest.TestCase):
    today=date(2026,11,27)
    @staticmethod
    def permit(number, issued):
        return Permit('ID','Canyon County',number,'2026-11-12','Building','Synthetic address',
            'Canyon County DSD Building Permit Tracker',CANYON_TRACKER,stage='APPLICATION',
            raw={'BP_PermitNumber':number,'BP_ReceivedDate':1794441600000,
                 'PemitIssued':'Permit Issued' if issued else None,'PermitIssuedDate':issued})

    def test_exact_civil_type_bounds(self):
        self.assertEqual(canyon_utc_civil(1795478400000,self.today),date(2026,11,24))
        for raw in (True,False,0,-1,1,"1795478400000",1795478400000.0,1795478400001,1798761600000,10**80):
            self.assertIsNone(canyon_utc_civil(raw,self.today),repr(raw))

    def test_counts_and_no_mutation(self):
        current=[self.permit('BP1',1795478400000),self.permit('BP2',None)]
        status={'source':'Canyon County','status':'ok','source_url':CANYON_TRACKER,'records_seen':len(current)}
        frozen=[p.to_dict() for p in current]
        docs=reporting_report([status],{'Canyon County':current},current,{p.key for p in current},{},'2026-11-27T00:38:54+00:00')
        row=docs['sources'][0]; counts=row['issued_evidence']
        self.assertEqual(row['observed_records'],2)
        self.assertEqual(row['latest_date_kind'],'application')
        self.assertEqual((counts['applications_examined'],counts['explicit_issue_observations'],counts['latest_explicit_issue_date']),(2,1,'2026-11-24'))
        self.assertEqual(set(counts),{'schema_version','source_url','scope','applications_examined','explicit_issue_observations','latest_explicit_issue_date'})
        self.assertTrue(all(p.stage=='APPLICATION' for p in current))
        self.assertEqual([p.to_dict() for p in current],frozen)

    def test_error_wrong_scope_conflicts_and_non_evidence(self):
        x=self.permit('BP1',1795478400000)
        status={'status':'ok','source_url':CANYON_TRACKER,'records_seen':1}
        for bad in [{**status,'status':'error'},{**status,'source_url':CANYON_TRACKER[:-1]+'0'},{**status,'records_seen':2}]:
            self.assertIsNone(canyon_issue_evidence(bad,[x],self.today))
        altered=copy.deepcopy(x)
        altered.raw['BP_PermitNumber']='wrong'
        self.assertIsNone(canyon_issue_evidence(status,[altered],self.today))
        altered=copy.deepcopy(x)
        altered.raw['PermitIssuedDate']=None
        counts=canyon_issue_evidence(status,[altered],self.today)
        self.assertEqual(counts['explicit_issue_observations'],0)
        self.assertIsNone(counts['latest_explicit_issue_date'])
        self.assertIsNone(canyon_issue_evidence({**status,'records_seen':2},[x,altered],self.today))
        self.assertEqual(canyon_issue_evidence({**status,'records_seen':2},[x,x],self.today)['explicit_issue_observations'],1)
