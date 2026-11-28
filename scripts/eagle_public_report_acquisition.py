"""Acquire official Eagle weekly PDFs through the normal public WebLink UI.

Read-only. Stop on access restrictions, login, robot challenge or robots denial.
No guessed document IDs, private API calls, tracker writes or publication.
"""
import argparse
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urljoin, parse_qs
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.robotparser import RobotFileParser

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

HOST = "lf.cityofeagle.org"
ROOT = "https://" + HOST
FOLDER = ROOT + "/WebLink/Browse.aspx?id=100694&dbid=0&repo=CityofEagle"
PUBLIC_ENTRY = ROOT + "/WebLink/?dbid=0&repo=CityofEagle"
UA = "EaglePermitReportResearch"
RESTRICT = re.compile(r"verify (?:that )?you(?:'re| are) not a robot|human verification|captcha|access denied|sign in to continue|login required|authentication required", re.I)
REPORT = re.compile(r"^Building Permit Report\s*[-–]\s*(\d{1,2})[-./](\d{1,2})[-./](\d{4})$", re.I)

def check_robots():
    r = requests.get(ROOT + "/robots.txt", headers={"User-Agent": UA}, timeout=15, allow_redirects=False)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RuntimeError("robots policy unavailable: HTTP " + str(r.status_code))
    parser = RobotFileParser()
    parser.parse(r.text.splitlines())
    if not all(parser.can_fetch(UA, u) for u in (PUBLIC_ENTRY, FOLDER)):
        raise RuntimeError("robots policy prohibits report acquisition")
    return parser

def allowed_url(url, robots):
    u = urlsplit(url)
    return u.scheme == "https" and u.netloc == HOST and (robots is None or robots.can_fetch(UA, url))

def report_date(label):
    m=REPORT.fullmatch(label.strip())
    if not m: return None
    try: return datetime(int(m[3]),int(m[1]),int(m[2])).date()
    except ValueError: return None

def public_href(url, robots, kind):
    if not allowed_url(url, robots): return False
    u=urlsplit(url)
    q=parse_qs(u.query)
    return (u.path.lower()=="/weblink/"+kind.lower()+".aspx"
            and q.get("repo")==["CityofEagle"] and q.get("dbid")==["0"]
            and len(q.get("id",[]))==1 and q["id"][0].isdigit())

def discover_reports(page, guard, robots):
    """Follow only visible report-related directory links from the supplied parent."""
    today=datetime.now(ZoneInfo("America/Boise")).date()
    cutoff=today-timedelta(days=45)
    years={str(today.year), str(cutoff.year)}
    months=set()
    for i in range(46):
        day=today-timedelta(days=i)
        months.add(day.strftime("%B").lower())
        months.add(day.strftime("%b").lower())
        months.add(str(day.month))
        months.add(f"{day.month:02}")
    queue=[FOLDER]; seen=set(); reports={}
    while queue and len(seen)<14:
        url=queue.pop(0)
        id_=parse_qs(urlsplit(url).query).get("id",[""])[0]
        if id_ in seen: continue
        seen.add(id_)
        page.goto(url,wait_until="domcontentloaded",timeout=30000)
        page.wait_for_timeout(1500)
        guard()
        links=[]
        for fr in page.frames:
            links.extend(fr.locator("a[href]").evaluate_all("(els)=>els.filter(e=>e.getClientRects().length).map(e=>({label:(e.innerText||e.textContent||'').trim().replace(/\\s+/g,' '),href:e.href}))"))
        dirs=[]
        for l in links:
            label=l["label"]; href=l["href"]
            if not label or len(label)>100: continue
            d=report_date(label)
            if d and cutoff<=d<=today and public_href(href,robots,"DocView"):
                reports[href]=(d,label,href,page.url)
            elif public_href(href,robots,"Browse"):
                low=label.lower().strip()
                match=("building permit report" in low or low in years or low in months
                    or any(re.fullmatch(r"(?:\d{1,2}\s*[-. ]\s*)?"+re.escape(m)+r"(?:\s+20\d{2})?",low) for m in months)
                    or bool(re.fullmatch(r"(?:building permit reports?\s*[-–]?\s*)?(?:"+"|".join(years)+r")",low)))
                if match:
                    dirs.append((label,href))
                    if parse_qs(urlsplit(href).query).get("id",[""])[0] not in seen: queue.append(href)
        print(json.dumps({"directory":page.url,"report_folders":dirs,"dated_reports":len(reports)}),flush=True)
    result=sorted(reports.values(),reverse=True)
    if len(result)<2:
        raise RuntimeError("Parent directory did not expose two recent weekly reports; inspect directory navigation evidence")
    return result[:2]

def verify_pdf(path):
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-") or len(raw) > 100_000_000:
        raise RuntimeError("not a bounded PDF")
    from eagle_report_parser import parse_report
    result = parse_report(path)
    counts = {}
    source_categories = {}
    candidate_label_misses = {}
    for row in result["records"]:
        kind = row["candidate_type"] or "other"
        counts[kind] = counts.get(kind, 0) + 1
        # Aggregate only category labels, not owner, address or contractor information.
        pair = (row["report_type"], row["use_class"])
        source_categories[pair] = source_categories.get(pair, 0) + 1
        if not row["candidate_type"] and row["use_class"].startswith(("New Home","New Commerc")):
            # Diagnostics intentionally contain only source category and a bounded
            # allowlisted scope indicator, never free-text owner/project details.
            desc=row["description"]
            scope=desc if desc in {"New Home","New Commercial","New Townhome","Core & shell construction"} else "other source scope"
            key=pair+(scope,)
            candidate_label_misses[key]=candidate_label_misses.get(key,0)+1
    return {k:v for k,v in result.items() if k!="records"} | {
        "bytes":len(raw), "candidate_counts":counts,
        "source_category_counts":[{"report_type":k[0],"use_class":k[1],"count":v} for k,v in sorted(source_categories.items())],
        "unmapped_new_label_counts":[{"report_type":k[0],"use_class":k[1],"scope":k[2],"count":v} for k,v in sorted(candidate_label_misses.items())],
        "candidate_valuation":sum(r["valuation"] for r in result["records"] if r["candidate_type"])}


def main():
    args=argparse.ArgumentParser()
    args.add_argument('--output',type=Path,help='Temporary collector input, not a public export')
    options=args.parse_args()
    robots = check_robots()
    restricted = []
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch(headless=True, channel="chrome")
        context = browser.new_context(accept_downloads=True, user_agent=UA + " (public permit report research)")
        # No stealth, challenge solving, authentication, or private endpoints.
        def route_handler(route):
            req = route.request
            u = urlsplit(req.url)
            if u.scheme not in ("http", "https"):
                return route.continue_()
            if u.netloc == HOST and not allowed_url(req.url, robots):
                restricted.append("robots")
                return route.abort()
            return route.continue_()
        context.route("**/*", route_handler)
        page = context.new_page()
        page.set_default_timeout(8000)
        def observe(response):
            if urlsplit(response.url).netloc == HOST and response.status in (401,403,429):
                restricted.append(str(response.status))
        context.on("response", observe)
        def guard():
            if restricted:
                raise RuntimeError("restricted public archive response: " + ",".join(sorted(set(restricted))))
            for pg in context.pages:
                if pg.is_closed() or pg.url == "about:blank":
                    continue
                if not allowed_url(pg.url, robots):
                    raise RuntimeError("unexpected or restricted viewer location")
                for fr in pg.frames:
                    try:
                        body = fr.locator("body").inner_text(timeout=3000)
                    except PlaywrightTimeout:
                        continue
                    if RESTRICT.search(body):
                        raise RuntimeError("public archive requires verification or authentication")
        def entries():
            found = []
            for fr in page.frames:
                for item in fr.locator("a, button, [role=link], [role=row], [role=treeitem]").all()[:300]:
                    try:
                        if not item.is_visible():
                            continue
                        label = " ".join(item.inner_text(timeout=1000).split())
                        if label and len(label) <= 180 and REPORT.search(label):
                            found.append((label,item))
                    except PlaywrightTimeout:
                        continue
            return found
        try:
            discovered = discover_reports(page, guard, robots)
            print(json.dumps({"discovered_reports":[{"date":d.isoformat(),"title":l,"url":u} for d,l,u,f in discovered]}),flush=True)
            acquired=[]
            payload=[]
            downloads, pdf_responses=[], []
            def capture(response):
                if allowed_url(response.url, robots) and response.status==200 and "application/pdf" in response.headers.get("content-type","").lower():
                    pdf_responses.append(response)
            context.on("response",capture)
            def attach(new_page):
                new_page.on("download",lambda download: downloads.append(download))
            context.on("page",attach)
            attach(page)
            for report_day, report_title, report_href, report_folder in discovered:
                for viewer in context.pages:
                    if viewer!=page: viewer.close()
                page.goto(report_folder,wait_until="domcontentloaded",timeout=30000)
                page.wait_for_timeout(1500)
                guard()
                selected=[(label,item) for label,item in entries() if label==report_title and urljoin(page.url,item.get_attribute("href") or "")==report_href and public_href(report_href,robots,"DocView")]
                if len(selected)!=1:
                    raise RuntimeError("discovered report is not a unique visible document link")
                downloads.clear(); pdf_responses.clear()
                selected[0][1].click(timeout=5000)
                for _ in range(16):
                    page.wait_for_timeout(1000)
                    guard()
                    if downloads or pdf_responses: break
                dest=Path(tmp)/("report-"+report_day.isoformat()+".pdf")
                if downloads:
                    downloads[0].save_as(dest)
                elif pdf_responses:
                    dest.write_bytes(pdf_responses[0].body())
                else:
                    raise RuntimeError("public report viewer did not deliver a PDF")
                from eagle_report_parser import parse_report
                parsed=parse_report(dest)
                summary=verify_pdf(dest)
                if parsed["period_start"]!=report_day.isoformat():
                    raise RuntimeError("document period does not match directory label")
                # Official report explicitly lists issuance date and source column names.
                if parsed["sha256"]=="55864c0276a4c958d7fcc0501e8a1c425ce78a9fd26f7b2814e90404ed606295":
                    assert parsed["visible_total"]==34 and parsed["printed_total"]==35
                    assert summary["candidate_counts"]=={"New single-family dwelling":18,"other":11,"New townhome":3,"New commercial construction":2}
                    assert summary["candidate_valuation"]==16841106
                payload.append({"document_url":report_href,"title":report_title,**parsed})
                acquired.append({"document_url":report_href,"title":report_title,**summary})
            if len(payload)!=2 or len({x["sha256"] for x in payload})!=2:
                raise RuntimeError("two distinct reports required")
            if options.output:
                options.output.write_text(json.dumps(payload),encoding="utf-8")
            print(json.dumps({"acquired":acquired,"production_writes":0}),flush=True)
        finally:
            browser.close()

if __name__ == "__main__":
    main()
