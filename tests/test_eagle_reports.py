from datetime import date
import copy
import unittest
from idaho_permits.collectors.eagle_reports import parse_batch

TODAY=date(2026,11,27)

def record(n,d):
    return dict(permit_number=n,issued_date=d,address='Example fixture street',
                subdivision='Fixture',apn=None,contractor='Fixture Company',
                valuation=100000,living_area_sqft=1000,description='New Home',
                report_type='Building Residenti',use_class='New Home-',
                candidate_type='New single-family dwelling',source_page=1)

def report(number,day,row,total):
    return dict(document_url=f'https://lf.cityofeagle.org/WebLink/DocView.aspx?id={number}&dbid=0&repo=CityofEagle',
                sha256=str(number)*64,period_start=day,period_end=day,
                visible_total=1,printed_total=total,complete=(total==1),records=[row])

class EagleReportAdapterTests(unittest.TestCase):
    def setUp(self):
        self.payload=[report(1,'2026-11-16',record('100001','2026-11-16'),1),
                      report(2,'2026-11-20',record('100002','2026-11-20'),1)]
    def test_complete(self):
        r=parse_batch(self.payload,TODAY)
        self.assertEqual(r.status,'ok')
        self.assertEqual(len(r.permits),2)
        self.assertEqual(r.latest_issued_date,'2026-11-20')
    def test_observed_alternate_city_labels(self):
        row=self.payload[0]['records'][0]
        row.update(report_type='Building Residential',use_class='New Home Single')
        self.assertEqual(parse_batch(self.payload,TODAY).permits[0].permit_type,'New single-family dwelling')
        row.update(description='New Commercial',report_type='Building Commercial',
                   use_class='New Commerci',candidate_type='New commercial construction')
        self.assertEqual(parse_batch(self.payload,TODAY).permits[0].permit_type,'New commercial construction')
        row.update(description='Occupancy Only',candidate_type='New commercial construction')
        with self.assertRaisesRegex(ValueError,'candidate mapping'):
            parse_batch(self.payload,TODAY)
    def test_missing_total_is_partial(self):
        self.payload[0].update(printed_total=None,complete=False)
        r=parse_batch(self.payload,TODAY)
        self.assertEqual(r.status,'degraded')
        self.assertIsNone(r.permits[0].raw['report_printed_total'])
    def test_total_mismatch_is_partial(self):
        self.payload[0].update(printed_total=2,complete=False)
        self.assertEqual(parse_batch(self.payload,TODAY).status,'degraded')
    def test_false_completeness_rejected(self):
        self.payload[0].update(printed_total=None,complete=True)
        with self.assertRaisesRegex(ValueError,'count reconciliation'):
            parse_batch(self.payload,TODAY)
    def test_duplicate_record_rejected(self):
        self.payload[1]['records'][0]['permit_number']='100001'
        with self.assertRaisesRegex(ValueError,'duplicate'):
            parse_batch(self.payload,TODAY)
    def test_bad_source_link_rejected(self):
        self.payload[0]['document_url']='https://example.test/report'
        with self.assertRaisesRegex(ValueError,'report evidence'):
            parse_batch(self.payload,TODAY)
    def test_mismatched_type_rejected(self):
        self.payload[0]['records'][0]['description']='Occupancy Only'
        with self.assertRaisesRegex(ValueError,'candidate mapping'):
            parse_batch(self.payload,TODAY)
    def test_issue_outside_period_rejected(self):
        self.payload[0]['records'][0]['issued_date']='2026-11-17'
        with self.assertRaisesRegex(ValueError,'issue date'):
            parse_batch(self.payload,TODAY)
