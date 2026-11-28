"""City of Eagle weekly issued report collector, restricted to explicit new buildings.

Report-level links and hashes are retained. Incomplete printed totals are visible
as degraded coverage, not inferred zero or a full city inventory.
"""
from datetime import date
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit,parse_qs
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta

from .base import CollectorResult
from ..models import Permit
from ..classify import classify_permit

SOURCE="City of Eagle weekly building permit report"
DIRECTORY="https://lf.cityofeagle.org/WebLink/Browse.aspx?id=100694&dbid=0&repo=CityofEagle"
SCRIPT=Path(__file__).resolve().parents[3]/"scripts"/"eagle_public_report_acquisition.py"
KINDS={
    ("Building Residenti","New Home-","New Home"):"New single-family dwelling",
    ("Building Residential","New Home Single","New Home"):"New single-family dwelling",
    ("Building Commercial","New Commerci","New Commercial"):"New commercial construction",
    ("Building Commercial","New Commerci","Core & shell construction"):"New commercial construction",
    ("Building Residenti","New Home-","New Townhome"):"New townhome",
    ("Building Commer","New Commerc","New Commercial"):"New commercial construction",
    ("Building Commer","New Commerc","Core & shell construction"):"New commercial construction",
}

def enabled():
    return os.getenv("EAGLE_REPORT_FALLBACK")=="1"

def local_today():
    return datetime.now(ZoneInfo("America/Boise")).date()

def source_link(url):
    u=urlsplit(url); q=parse_qs(u.query)
    return (u.scheme=="https" and u.netloc=="lf.cityofeagle.org" and
        u.path.lower()=="/weblink/docview.aspx" and q.get("dbid")==["0"] and
        q.get("repo")==["CityofEagle"] and len(q.get("id",[]))==1 and q["id"][0].isdigit())

def parse_batch(payload,today=None):
    today=today or local_today()
    if not isinstance(payload,list) or len(payload)!=2:
        raise ValueError("expected two recent official reports")
    ids=set(); hashes=set(); periods=set(); urls=set(); permits=[]; partial=False
    source_total=visible_total=0; missing_controls=0; issue_dates=[]; end_dates=[]
    for report in payload:
        if not isinstance(report,dict): raise ValueError("invalid report")
        lo=date.fromisoformat(report["period_start"]); hi=date.fromisoformat(report["period_end"])
        if lo<today-timedelta(days=45) or hi>today or not 0<=(hi-lo).days<=7 or lo in periods:
            raise ValueError("unexpected recent report period")
        hash_=report["sha256"]; url=report["document_url"]; rows=report["records"]
        if not re.fullmatch(r"[0-9a-f]{64}",hash_) or hash_ in hashes or not source_link(url) or url in urls:
            raise ValueError("invalid or repeated report evidence")
        visible=report["visible_total"]; total=report["printed_total"]
        if type(visible) is not int or not isinstance(rows,list) or visible!=len(rows) or not 1<=visible<=500 or (total is not None and (type(total) is not int or not visible<=total<=500)) or type(report["complete"]) is not bool or report["complete"]!=(total is not None and visible==total):
            raise ValueError("report count reconciliation failed")
        if total is None: missing_controls+=1
        else: source_total+=total
        visible_total+=visible; partial|=total is None or visible!=total
        periods.add(lo); hashes.add(hash_); urls.add(url); end_dates.append(hi)
        for r in rows:
            n=r["permit_number"]; issued=date.fromisoformat(r["issued_date"])
            if not re.fullmatch(r"\d{4,12}",n) or n in ids or not lo<=issued<=hi or not isinstance(r["address"],str) or not r["address"].strip():
                raise ValueError("invalid or duplicate permit ID, address or issue date")
            ids.add(n); issue_dates.append(issued)
            value=r["valuation"]; living=r["living_area_sqft"]
            if type(value) is not int or value<0 or type(living) is not int or living<0:
                raise ValueError("invalid source numeric field")
            expected=KINDS.get((r["report_type"],r["use_class"],r["description"]))
            if r["candidate_type"]!=expected: raise ValueError("unsupported candidate mapping")
            if not expected: continue
            contractor=r["contractor"]
            if contractor is not None and (not isinstance(contractor,str) or not contractor.strip()):
                raise ValueError("invalid source contractor")
            p=Permit("ID","Eagle",n,issued.isoformat(),expected,r["address"],SOURCE,url,
                project_name=r["description"],building_use=expected,valuation=value,
                contractor=contractor,apn=r["apn"],subdivision=r["subdivision"] or None,
                status="Issued (weekly report)",city="Eagle",county="Ada",stage="PERMITTED",
                raw={"issue_date_verified":True,"contractor_role":"Contractor (city report)" if contractor else None,
                     "report_sha256":hash_,"report_period_start":lo.isoformat(),"report_period_end":hi.isoformat(),
                     "report_printed_total":total,"report_visible_total":visible,
                     "report_complete":report["complete"],"source_page":r["source_page"],
                     "source_permit_type":r["report_type"],"source_use_class":r["use_class"],
                     "source_description":r["description"],"living_area_sqft":living,
                     "source_valuation":value})
            classify_permit(p)
            if not p.qualifies: raise ValueError("explicit building candidate failed unchanged classifier")
            permits.append(p)
    if not issue_dates:
        raise ValueError("no verified issuance evidence")
    # Two distinct, non-overlapping report windows; a partial count never asserts completeness.
    ordered=sorted((date.fromisoformat(r["period_start"]),date.fromisoformat(r["period_end"])) for r in payload)
    if ordered[0][1]>=ordered[1][0]: raise ValueError("overlapping report periods")
    latest=max(issue_dates); stale=(today-latest).days>14
    note=(f"Official Eagle weekly reports: {visible_total} distinct visible records; printed total {source_total} across reports with controls, {missing_controls} report(s) without a control total; "
          f"{len(permits)} explicit new-building candidates. Source-reported contractor, not independent GC verification. "
          f"Latest verified issue {latest.isoformat()}; report periods end {max(end_dates).isoformat()}. "
          "Existing identities preserved; no inferred missing records.")
    if partial: note+=" Missing or mismatched control total: partial report coverage."
    if stale: note+=" Source older than 14 days."
    return CollectorResult("Eagle",DIRECTORY,permits,note,status="degraded" if partial or stale else "ok",
        latest_issued_date=latest.isoformat(),report_period_end=max(end_dates).isoformat())

def collect_reports():
    with tempfile.TemporaryDirectory(prefix="eagle-official-") as tmp:
        out=Path(tmp)/"reports.json"
        try:
            result=subprocess.run([sys.executable,str(SCRIPT),"--output",str(out)],timeout=180,
                                  capture_output=True,text=True,check=True)
            if not out.is_file() or out.stat().st_size>2_000_000:
                raise ValueError("missing or oversized verified report output")
            return parse_batch(json.loads(out.read_text(encoding="utf-8")))
        except subprocess.CalledProcessError as e:
            # Bounded diagnostics, no row data or owner details.
            err=(e.stderr or "").strip().splitlines()
            raise RuntimeError("Eagle public report acquisition failed: "+(err[-1][:260] if err else "unknown")) from e
        except (subprocess.TimeoutExpired,OSError,ValueError,KeyError,TypeError) as e:
            raise RuntimeError("Eagle public report acquisition failed: "+str(e)[:260]) from e
