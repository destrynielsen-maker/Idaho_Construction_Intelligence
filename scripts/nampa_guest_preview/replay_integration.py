"""Use captured hosted municipal evidence in the real Nampa collector and pipeline, never publish."""
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from datetime import date

from idaho_permits import pipeline
from idaho_permits.collectors.nampa import NampaPermitCollector

def run(baseline, municipal):
    from test_nampa_november_release_gate import audit_paths
    lo, hi = date(2026, 11, 23), date(2026, 11, 27)
    assert json.loads(municipal)['period'] == {'lo': lo.isoformat(),'hi': hi.isoformat()}
    with TemporaryDirectory(prefix='nampa-preview-') as tmp:
        dest=Path(tmp)
        shutil.copytree(baseline/'data', dest/'data')
        shutil.copytree(baseline/'public', dest/'public')
        with patch.dict(os.environ, {'NAMPA_CSS_FALLBACK':'1',
                    'SITE_BASE_URL':'https://destrynielsen-maker.github.io/Idaho_Construction_Intelligence/'}), \
             patch.object(pipeline,'COLLECTORS',[NampaPermitCollector()]), \
             patch.object(NampaPermitCollector,'_collect_pdf',side_effect=RuntimeError('offline PDF failure control')), \
             patch('idaho_permits.collectors.nampa_css.collect_css',side_effect=lambda: collect_css_window(municipal,lo,hi)):
            run1=pipeline.run(dest)
            stable=(dest/'data/permits.json').read_bytes()
            run2=pipeline.run(dest)
        a=json.loads(stable)['permits']
        b=json.loads((dest/'data/permits.json').read_bytes())['permits']
        assert a == b, 'replaying verified IDs must not alter records'
        assert run1['total_stored']==run2['total_stored']
        assert run1['sources'][0]['status']=='degraded'
        print(json.dumps(audit_paths(baseline,dest),indent=2))

def collect_css_window(data,lo,hi):
    from idaho_permits.collectors.nampa_css import parse_batch
    return parse_batch(json.loads(data),lo,hi)

if __name__=='__main__':
    run(Path(sys.argv[1]),Path(sys.argv[2]).read_text(encoding='utf-8'))
