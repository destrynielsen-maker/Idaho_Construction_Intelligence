from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import os
import runpy
import unittest
from unittest.mock import patch

from idaho_permits import pipeline
from idaho_permits.collectors.coeur_dalene import CoeurDAleneCollector, REPORT_URL
from idaho_permits.models import Permit
from idaho_permits.storage import load_permits, save_permits
from test_cda_source import FixedDate, MODULE, response


def fixture(n, day, address):
    return f'''
Permit Num:
Owner:
Address: {address} Project: DUPLEX W/GARAGE
Issued: Valuation: Type:
{n}-B
Duplex08/{day}/2026Example Owner LLC $450,000.00
Contractor: EXAMPLE HOMES LLC
'''


class TestCdaRecovery(unittest.TestCase):
    def test_entrypoint_outage_empty_pdf_then_recovery_and_repeat(self):
        c=CoeurDAleneCollector()
        prior=Permit('ID',c.name,'152695-B','2026-08-17','New Multifamily Duplex',
                     'Fixture address',c.name,REPORT_URL,contractor='EXAMPLE HOMES LLC',
                     first_seen_at='2026-08-18',last_seen_at='2026-08-22')
        good=fixture('152695','17','100 EXAMPLE')+fixture('152696','27','102 EXAMPLE')
        valid=response(200,b'%PDF-1.4 fixture','application/pdf')
        with TemporaryDirectory() as tmp, patch.object(pipeline,'COLLECTORS',[c]), \
                patch(MODULE+'.date',FixedDate), \
                patch(MODULE+'.requests.post',side_effect=[response(500,b'error'),valid,valid,valid]), \
                patch(MODULE+'.pdf_text',side_effect=['Unexpected format',good,good]):
            store=Path(tmp)/'data'/'permits.json'; save_permits(store,[prior],'2026-08-22')
            cwd=os.getcwd()
            try:
                os.chdir(tmp)
                for count, expected in enumerate(('error','error','ok','ok'),1):
                    out=io.StringIO()
                    with redirect_stdout(out): runpy.run_module('idaho_permits.main',run_name='__main__')
                    status,=json.loads(out.getvalue())['sources']
                    self.assertEqual(status['status'],expected)
                    records=load_permits(store)
                    self.assertIn(prior.key,records)
                    self.assertEqual(records[prior.key].first_seen_at,'2026-08-18')
                    self.assertEqual(len(records),1 if count<3 else 2)
                    if count<3:
                        self.assertEqual(records[prior.key].last_seen_at,'2026-08-22')
                    else:
                        qualified=json.loads(Path('public/data/permits.json').read_text())['permits']
                        self.assertEqual({x['permit_number'] for x in qualified},{'152695-B','152696-B'})
            finally:
                os.chdir(cwd)
