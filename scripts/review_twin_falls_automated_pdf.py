"""Review automated extraction on genuine county PDFs and manual oracle."""
import json
from decimal import Decimal
from pathlib import Path
from idaho_permits.county_intake import read_batch
from idaho_permits.twin_falls_county_pdf import fetch_reports, parse_pdf

def norm(s):
    return "".join(c for c in s.upper() if c.isalnum())

seen=set()
for month,url,content in fetch_reports():
    records=parse_pdf(content,month,url)
    expected_path=Path("tests/fixtures")/f"twin_falls_county_{month}.csv"
    assert expected_path.exists(), "new publisher month needs independent reconciliation"
    expected={r["permit_number"]:r for r in read_batch(expected_path,{"2026-09":30,"2026-10":19}[month]).values()}
    assert set(expected)==set(records) and not seen.intersection(records)
    seen.update(records)
    differences=[]
    for number,r in records.items():
        e=expected[number]
        assert r["issued_date"]==e["issued_date"] and r["source_page"]==int(e["source_page"])
        assert Decimal(r["valuation_decimal"])==Decimal(e["valuation"] or "0")
        for field in ["permit_type","work_type","contractor","project_address"]:
            a,b=norm(r[field]),norm(e[field])
            if a!=b:
                differences.append({"number":number,"field":field,"actual":r[field],"oracle":e[field]})
    print(json.dumps({"month":month,"source":url,"rows":len(records),"latest":max(r["issued_date"] for r in records.values()),"differences":differences},indent=2),flush=True)
    assert not differences,"manual oracle differences require human/source review; do not publish"
assert len(seen)==49
