from types import SimpleNamespace
from datetime import date
import unittest
from unittest.mock import patch

import requests
from idaho_permits.collectors.report_pages import MeridianDirectCollector


def index_response(url):
    return SimpleNamespace(url=url,text='''
    <a href="/media/2supipdx/weekly-reports-1122026-1182026.pdf">Week 1</a>
    <a href="/media/dh5iko1f/weekly-reports-1192026-11152026.pdf">Week 2</a>
    <a href="/media/0v2dk25y/weekly-reports-11162026-11222026.pdf">Week 3</a>
    <a href="/media/eo1lxput/weekly-reports-10262026-1112026.pdf">Week 4</a>
    <a href="/media/radihw1g/bldgmonthlypermits.pdf">Full Report</a>
    <a href="https://foreign.example/media/skip.pdf">Week 5</a>''')

def report(day):
    return f'CITY OF MERIDIAN\nBUILDING PERMITS FOR THE WEEK\nIssued:\n11/{day}/2026'

class FrozenDate(date):
    @classmethod
    def today(cls): return cls(2026,11,26)

class TestMeridianIndexDiscovery(unittest.TestCase):
    def setUp(self):
        self.c=MeridianDirectCollector()
        self.calls=[]
        self.first_error=requests.Timeout()
        self.alt_error=None
        self.content={
            self.c.seed_reports[0][1]:report(20),
            self.c.seed_reports[1][1]:report(13),
            self.c.seed_reports[2][1]:report(6),
            self.c.seed_reports[3][1]:'OCT 2026\nCITY OF MERIDIAN\nBUILDING PERMITS FOR THE MONTH\nIssued: 10/30/2026',
        }
    def fetch(self,url,**kwargs):
        self.calls.append(url)
        if url==self.c.landing_url:
            if self.first_error: raise self.first_error
            return index_response(url)
        if url==self.c.alternate_index_url:
            if self.alt_error: raise self.alt_error
            return index_response(url)
        return SimpleNamespace(url=url,content=b'%PDF'+self.content[url].encode())
    def run_collector(self):
        module='idaho_permits.collectors.report_pages'
        with patch(module+'.get',side_effect=self.fetch),patch(module+'.pdf_text',lambda b:b[4:].decode()),patch(module+'.date',FrozenDate):
            return self.c.collect()
    def test_timeout_falls_back_to_publisher_index_without_rewriting_seeds(self):
        result=self.run_collector()
        self.assertEqual(self.calls[:2],[self.c.landing_url,self.c.alternate_index_url])
        self.assertEqual(set(self.calls[2:]),set(self.content))
        self.assertIn('standard index used',result.note)
        self.assertIn('Week 4 points to earlier period ending 2026-11-01',result.note)
        self.assertEqual((result.latest_issued_date,result.report_period_end),('2026-11-20','2026-11-22'))
    def test_explicit_access_denial_does_not_use_alternate_index(self):
        response=requests.Response();response.status_code=403
        self.first_error=requests.HTTPError(response=response)
        result=self.run_collector()
        self.assertNotIn(self.c.alternate_index_url,self.calls)
        self.assertEqual(set(self.calls[1:]),set(self.content))
        self.assertIn('City index unavailable (403)',result.note)
    def test_both_indexes_unavailable_still_use_all_four_official_seeds(self):
        self.alt_error=requests.Timeout()
        result=self.run_collector()
        self.assertEqual(set(self.calls[2:]),set(self.content))
        self.assertEqual(result.report_period_end,'2026-11-22')
    def test_new_independent_week_is_discovered_and_validated_from_body(self):
        good=index_response(self.c.alternate_index_url)
        asset='https://meridiancity.org/media/new/weekly-reports-11232026-11292026.pdf'
        good.text=good.text.replace('/media/eo1lxput/weekly-reports-10262026-1112026.pdf',asset)
        self.content[asset]=report(25)
        original=self.fetch
        def fetch(url,**kwargs):
            return good if url==self.c.alternate_index_url else original(url,**kwargs)
        self.fetch=fetch
        result=self.run_collector()
        self.assertEqual((result.status,result.latest_issued_date,result.report_period_end),('ok','2026-11-25','2026-11-29'))
        self.assertEqual(result.source_url,asset)
