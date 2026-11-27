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

# Read-only integration replay on the ledger in this exact candidate tree.
# A conflict is reported as a release blocker, never silently suppressed.
from copy import deepcopy
from tempfile import TemporaryDirectory
from idaho_permits.storage import load_permits, save_permits
from idaho_permits.dashboard import write_public_data
from idaho_permits.feeds import write_all_feeds
from xml.etree import ElementTree as ET

ledger = load_permits(Path("data/permits.json"))
original = {k: p.to_dict() for k, p in ledger.items()}
timestamp = "2026-11-27T00:00:00+00:00"
def append_only(existing, batch):
    result = deepcopy(existing)
    for k, p in batch.items():
        if k in result:
            old = result[k]
            if old.raw != p.raw or old.issued_date != p.issued_date:
                raise ValueError("existing identity has conflicting source evidence")
            continue
        q = deepcopy(p)
        q.first_seen_at = q.last_seen_at = timestamp
        result[k] = q
    return result

assert not set(ledger).intersection(permits), "existing county identities require reconciliation"
combined = append_only(ledger, permits)
assert len(combined) == len(ledger) + len(permits)
assert {k: combined[k].to_dict() for k in ledger} == original
# Exact replay and partial replay cannot remove or change historical records.
for batch in (permits, dict(list(permits.items())[:19]), {}):
    replay = append_only(combined, batch)
    assert {k: p.to_dict() for k,p in replay.items()} == {k: p.to_dict() for k,p in combined.items()}
# Conflicting re-observation is a failure, not an overwrite.
bad = deepcopy(next(iter(permits.values())))
bad.raw["description"] = "conflicting observation"
try:
    append_only(combined, {bad.key: bad})
except ValueError:
    pass
else:
    raise AssertionError("conflicting evidence accepted")

def outputs(root, records):
    write_public_data(root, list(records.values()), [], timestamp)
    write_all_feeds(root / "feeds", list(records.values()), "https://example.invalid/")
    published = json.loads((root / "data" / "permits.json").read_text())["permits"]
    builders = json.loads((root / "data" / "builders.json").read_text())
    feeds = {}
    for file in (root / "feeds").glob("*.xml"):
        entries = ET.parse(file).findall("./channel/item")
        feeds[file.name] = {e.findtext("guid"): (e.findtext("title"), e.findtext("link"), e.findtext("description")) for e in entries}
        assert len(entries) == len(feeds[file.name])
    return {p["key"]: p for p in published}, {b["contractor"]: b for b in builders}, feeds

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    save_permits(root/"ledger.json", list(combined.values()), timestamp)
    restored = load_permits(root/"ledger.json")
    assert {k:p.to_dict() for k,p in restored.items()} == {k:p.to_dict() for k,p in combined.items()}
    before, builders_before, feeds_before = outputs(root/"before", ledger)
    after, builders_after, feeds_after = outputs(root/"after", combined)
    new_qual = {k:p for k,p in permits.items() if p.qualifies}
    assert set(after) - set(before) == set(new_qual)
    assert all(after[k] == p for k,p in before.items())
    for name in set(builders_before) | set(builders_after):
        a, b = builders_before.get(name, {}), builders_after.get(name, {})
        new = [p for p in new_qual.values() if p.contractor == name]
        assert b.get("count", 0) - a.get("count", 0) == len(new)
        assert b.get("score_total", 0) - a.get("score_total", 0) == sum(p.score for p in new)
        assert abs(b.get("valuation_total", 0) - a.get("valuation_total", 0) - sum(p.valuation or 0 for p in new)) < .01
    assert len(feeds_before) == len(feeds_after) == 5
    for name in feeds_before:
        a,b = feeds_before[name], feeds_after[name]
        assert all(b[k] == a[k] for k in a.keys() & b.keys())
        assert set(b) - set(a) <= set(new_qual)
        assert len(set(a) - set(b)) <= len(set(b) - set(a))
print(json.dumps({"review_only": True, "historical_preserved": len(ledger),
    "candidate_count":len(permits), "hypothetical_qualifying":len(new_qual),
    "replay_and_partial_preservation":True, "builder_delta_verified":True,
    "rss_delta_verified":True, "release_blockers": [
        "automatic report discovery not verified",
        "source classification conflicts require review" if conflicts else "final production acceptance outstanding"
    ]}, indent=2), flush=True)
