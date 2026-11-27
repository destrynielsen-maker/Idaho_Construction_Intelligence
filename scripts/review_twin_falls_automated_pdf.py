"""Review automated extraction on genuine county PDFs and manual oracle."""
import json
from decimal import Decimal
from pathlib import Path
from idaho_permits.county_intake import read_batch
import requests
from idaho_permits.twin_falls_county_pdf import official, parse_pdf

def norm(s):
    return "".join(c for c in s.upper() if c.isalnum())

seen=set()
# Extraction acceptance is independent of report-index discovery. The index
# returned HTTP 406 in run 45986290641; do not retry or bypass it here.
# These exact, previously publisher-linked PDFs are independently accessible
# and were reconciled successfully by review_twin_falls_county_sources.py.
# A successful extraction here does NOT demonstrate automated discovery.
print("REVIEW ONLY: known public PDF links; automated index discovery remains blocked (HTTP 406).",flush=True)
for month,count in [("2026-09",30),("2026-10",19)]:
    expected_path=Path("tests/fixtures")/f"twin_falls_county_{month}.csv"
    expected={r["permit_number"]:r for r in read_batch(expected_path,count).values()}
    urls={r["source_url"] for r in expected.values()}
    assert len(urls)==1
    url=urls.pop()
    assert official(url)
    response=requests.get(url,timeout=40)
    response.raise_for_status()
    assert official(response.url) and response.content.startswith(b"%PDF")
    records=parse_pdf(response.content,month,response.url)
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
