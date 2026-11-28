"""Read-only replay of actual downloaded Eagle reports on a copy of current-main data."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import math
import xml.etree.ElementTree as ET
from unittest.mock import patch
from collections import Counter

from idaho_permits import pipeline
from idaho_permits.collectors.eagle import EaglePermitCollector
from idaho_permits.collectors.eagle_reports import parse_batch
from idaho_permits.storage import load_permits

def ledger(path):
    return {k:p.to_dict() for k,p in load_permits(path).items()}

def stable(p):
    return {k:v for k,v in p.items() if k!="last_seen_at"}

def public(path):
    return {p["key"]:p for p in json.loads(path.read_text())["permits"]}

def builders(path):
    rows=json.loads(path.read_text())
    assert len({x["contractor"] for x in rows})==len(rows)
    return {x["contractor"]:x for x in rows}

def feed_items(path):
    rows=ET.parse(path).findall('./channel/item')
    for row in rows: row.tail=None
    result={r.findtext('guid'):ET.tostring(r,encoding='unicode') for r in rows}
    assert len(result)==len(rows) and all(result)
    return result

def compare_outputs(root, expected):
    old=builders(Path('public/data/builders.json'))
    prior_rank=list(old)
    prior_scores={k:(v['score_total'],v['count']) for k,v in old.items()}
    new=builders(root/'public/data/builders.json')
    for p in expected.values():
        name=p.get('contractor')
        if not name: continue
        row=old.setdefault(name,dict(contractor=name,count=0,score_total=0,valuation_total=0))
        row['count']+=1; row['score_total']+=p['score']; row['valuation_total']+=p['valuation'] or 0
    assert set(new)==set(old)
    for k,v in old.items():
        assert new[k]['count']==v['count'] and new[k]['score_total']==v['score_total']
        assert math.isclose(new[k]['valuation_total'],v['valuation_total'],abs_tol=0.01,rel_tol=0)
    # No reshuffling of equally-ranked unchanged builders.
    unchanged={k for k in prior_rank if prior_scores[k]==(new[k]['score_total'],new[k]['count'])}
    assert [k for k in prior_rank if k in unchanged]==[k for k in new if k in unchanged]
    for path in sorted(Path('public/feeds').glob('*.xml')):
        a=feed_items(path); b=feed_items(root/'public/feeds'/path.name)
        added=set(b)-set(a); removed=set(a)-set(b)
        assert added<=set(expected) and len(removed)<=len(added)
        if removed: assert len(b)==200
        assert all(a[k]==b[k] for k in set(a)&set(b))
        assert [k for k in a if k in b]==[k for k in b if k in a]

def main(source):
    payload=json.loads(Path(source).read_text())
    result=parse_batch(payload)
    before=ledger(Path("data/permits.json"))
    oldpub=public(Path("public/data/permits.json"))
    expected={p.key:p.to_dict() for p in result.permits if p.key not in before}
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        shutil.copytree("data",root/"data")
        shutil.copytree("public",root/"public")
        with patch.dict("os.environ",{"EAGLE_REPORT_FALLBACK":"1"}),patch.object(pipeline,"COLLECTORS",[EaglePermitCollector()]),patch("idaho_permits.collectors.eagle_reports.collect_reports",return_value=result):
            first=pipeline.run(root)
            after=ledger(root/"data/permits.json")
            published=public(root/"public/data/permits.json")
            compare_outputs(root,expected)
            first_feeds={p.name:feed_items(p) for p in (root/"public/feeds").glob("*.xml")}
            second=pipeline.run(root)
            assert first_feeds=={p.name:feed_items(p) for p in (root/"public/feeds").glob("*.xml")}
            repeated=ledger(root/"data/permits.json")
        assert before.keys()<=after.keys()
        assert set(after)-set(before)==set(expected)
        assert set(published)==set(oldpub)|set(expected)
        assert all(stable(before[k])==stable(after[k]) for k in before)
        assert all(stable(oldpub[k])==stable(published[k]) for k in oldpub)
        assert all(stable(after[k])==stable(repeated[k]) for k in after)
        assert len(after)==len(repeated)
        assert first["sources"][0]["latest_issued_date"]==result.latest_issued_date
        assert all(published[k]["source_url"]==v["source_url"] and published[k]["issued_date"]==v["issued_date"] for k,v in expected.items())
        print(json.dumps({"history_before":len(before),"history_after":len(after),"published_before":len(oldpub),"published_after":len(published),"added":len(expected),"qualifying_by_type":dict(Counter(v["classification"] for v in expected.values())),"new_valuation":sum(v["valuation"] for v in expected.values()),"already_existing":len(result.permits)-len(expected),"latest_issued":result.latest_issued_date,"status":result.status,"preserved":len(before),"repeat_no_duplicate":True,"production_writes":0}))
if __name__=="__main__":
    main(sys.argv[1])
