"""Read-only replay of actual downloaded Eagle reports on a copy of current-main data."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
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
            second=pipeline.run(root)
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
