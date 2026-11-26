from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from idaho_permits import pipeline
from idaho_permits.collectors.base import CollectorResult
from idaho_permits.models import Permit
from idaho_permits.storage import save_permits, load_permits


class FixtureCollector:
    name = 'Eagle'
    def collect(self):
        raise RuntimeError('unavailable')


class EmptyStaleCollector:
    name = 'Nampa'
    def collect(self):
        return CollectorResult('Nampa', 'https://example.invalid', [], status='stale')


class AuthoritativeEmptyCollector:
    name = 'Test authoritative source'
    def collect(self):
        return CollectorResult(self.name, 'https://example.invalid', [], note='Verified empty report')


class EagleResearchTests(unittest.TestCase):
    def test_evidence_history_never_changes_sales_or_erases_history(self):
        permits=[]
        for n, market, raw in [
            ('legacy-1','Eagle',{'listing':True}),
            ('verified-2','Eagle',{'listing':True,'issue_date_verified':True}),
            ('elsewhere-3','Meridian',{}),
        ]:
            permits.append(Permit('ID',market,n,'2026-11-10','New Single Family',
                                  'Fixture address','Fixture source','https://example.invalid',
                                  contractor=n,first_seen_at='2026-11-11',raw=raw))
        with TemporaryDirectory() as tmp:
            root=Path(tmp); store=root/'data'/'permits.json'
            save_permits(store,permits,'2026-11-11')
            with patch.object(pipeline,'COLLECTORS',[FixtureCollector(),EmptyStaleCollector(),AuthoritativeEmptyCollector()]):
                result=pipeline.run(root)
            public=root/'public'
            reader=lambda n:json.loads((public/'data'/n).read_text())
            historical=reader('eagle-research.json')['records']
            active=reader('permits.json')['permits']
            contractors={r['contractor'] for r in reader('builders.json')}
            self.assertEqual([r['legacy_reference'] for r in historical],['legacy-1'])
            self.assertEqual(historical[0]['legacy_listing_date'],'2026-11-10')
            self.assertEqual(historical[0]['evidence_status'],'unverified_historical')
            self.assertNotIn('contractor',historical[0])
            self.assertEqual({r['permit_number'] for r in active},{'verified-2','elsewhere-3'})
            self.assertEqual(contractors,{'verified-2','elsewhere-3'})
            for feed in (public/'feeds').glob('*.xml'):
                guids={g.text for g in ET.parse(feed).findall('.//guid')}
                self.assertNotIn(permits[0].key,guids)
            self.assertEqual(result['sources'][0]['count_scope'],'unavailable')
            self.assertIsNone(result['sources'][0]['records_seen'])
            self.assertEqual(result['sources'][1]['count_scope'],'partial_or_historical_snapshot')
            self.assertEqual(result['sources'][2]['count_scope'],'source_snapshot')
            self.assertEqual(result['sources'][2]['records_seen'],0)
            self.assertEqual(set(load_permits(store)),{p.key for p in permits})
            self.assertTrue(all(p.first_seen_at=='2026-11-11' for p in load_permits(store).values()))
