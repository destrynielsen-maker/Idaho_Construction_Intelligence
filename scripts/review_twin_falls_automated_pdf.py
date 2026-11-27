"""Review automated extraction on genuine county PDFs and manual oracle."""
import json
from decimal import Decimal
from pathlib import Path
from io import BytesIO
import re
import pdfplumber
from idaho_permits.county_intake import read_batch
import requests
from idaho_permits.twin_falls_candidate_review import review_candidates
from idaho_permits.twin_falls_county_pdf import official, parse_pdf, _layout, contractor_flow_candidates

def norm(s):
    return "".join(c for c in s.upper() if c.isalnum())

def norm_address(s):
    # Oracle is deliberately normalized to street/city; source extraction
    # retains full address. Only remove an explicit trailing Idaho ZIP from
    # this comparison, never from raw evidence.
    return norm(re.sub(r",?\s+ID\s+\d{5}(?:-\d{4})?\s*$","",s,flags=re.I))

seen=set()
all_rows=[]
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
    all_rows.extend(records.values())
    differences=[]
    for number,r in records.items():
        e=expected[number]
        assert r["issued_date"]==e["issued_date"] and r["source_page"]==int(e["source_page"])
        assert Decimal(r["valuation_decimal"])==Decimal(e["valuation"] or "0")
        for field in ["permit_type","work_type","contractor","project_address"]:
            normalize=norm_address if field=="project_address" else norm
            a,b=normalize(r[field]),normalize(e[field])
            if a!=b:
                differences.append({"number":number,"field":field,"actual":r[field],"oracle":e[field]})
    print(json.dumps({"month":month,"source":url,"rows":len(records),"latest":max(r["issued_date"] for r in records.values()),"differences":differences},indent=2),flush=True)
    if differences:
        # Read-only independent extraction diagnostics. Never replace a
        # contractor based on the fixture or the nearest owner/adjacent row.
        with pdfplumber.open(BytesIO(response.content)) as pdf:
            starts=_layout(pdf.pages[0].extract_words(x_tolerance=1.5,y_tolerance=2),pdf.pages[0].width)
            flow={}
            for page in pdf.pages:
                flow.update(contractor_flow_candidates(page,starts))
        for d in differences:
            if d["field"]=="contractor":
                print(json.dumps({"number":d["number"],"content_order_candidate":flow.get(d["number"]),
                    "oracle_match":norm(flow.get(d["number"],""))==norm(d["oracle"])}),flush=True)
    assert not differences,"manual oracle differences require human/source review; do not publish"
assert len(seen)==49

permits, conflicts = review_candidates(all_rows)
print(json.dumps({'review_only': True, 'tracker_candidates': len(permits), 'classifier_qualifying': sum(p.qualifies for p in permits.values()), 'classification_review_flags': conflicts}, indent=2), flush=True)
assert len(permits)==49
