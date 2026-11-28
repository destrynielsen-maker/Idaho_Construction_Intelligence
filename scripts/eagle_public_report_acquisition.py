"""Acquire official Eagle weekly PDFs through the normal public WebLink UI.

Read-only. Stop on access restrictions, login, robot challenge or robots denial.
No guessed document IDs, private API calls, tracker writes or publication.
"""
import hashlib
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
    for row in result["records"]:
        kind = row["candidate_type"] or "other"
        counts[kind] = counts.get(kind, 0) + 1
    return {k:v for k,v in result.items() if k!="records"} | {
        "bytes":len(raw), "candidate_counts":counts,
        "candidate_valuation":sum(r["valuation"] for r in result["records"] if r["candidate_type"])}


def main():
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
            # Prove the parent directory reaches the same PDF, using the latest discovered link.
            report_day, report_title, report_href, report_folder = discovered[0]
            page.goto(report_folder,wait_until="domcontentloaded",timeout=30000)
            page.wait_for_timeout(1500)
            guard()
            selected = [(label,item) for label,item in entries() if label==report_title and public_href(urljoin(page.url,item.get_attribute("href") or ""),robots,"DocView")]
            if len(selected)!=1:
                raise RuntimeError("discovered report is not a unique visible document link")
            acquired = []
            downloads = []
            pdf_responses = []
            def capture(response):
                if allowed_url(response.url, robots) and response.status == 200 and "application/pdf" in response.headers.get("content-type","").lower():
                    pdf_responses.append(response)
            context.on("response", capture)
            def attach(new_page):
                new_page.on("download", lambda download: downloads.append(download))
            context.on("page", attach)
            attach(page)

            # The WebLink folder may select a row on click and open on double click.
            # Follow actual public links, and inspect any new viewer tab.
            label, item = selected[0]
            print(json.dumps({"selected":label,"tag":item.evaluate("(e)=>e.tagName"),"href":item.get_attribute("href"),"title":item.get_attribute("title")}), flush=True)
            item.click(timeout=5000)
            page.wait_for_timeout(1500)
            guard()
            if not downloads and not pdf_responses and len(context.pages)==1 and "browse.aspx" in page.url.lower():
                item.dblclick(timeout=5000)
                page.wait_for_timeout(2500)
            def viewer_controls():
                result = []
                for pg in context.pages:
                    if pg.is_closed() or not allowed_url(pg.url, robots):
                        continue
                    for fr in pg.frames:
                        for ctl in fr.locator("a,button,input[type=button],input[type=submit],input[type=image],[role=button],[title],[aria-label],[data-original-title],[data-bs-original-title],img[alt],svg").all()[:500]:
                            try:
                                if not ctl.is_visible():
                                    continue
                                values = [ctl.get_attribute(k) or "" for k in ("title","aria-label","value","alt","data-original-title","data-bs-original-title")]
                                values.append(ctl.inner_text(timeout=500))
                                values.extend(ctl.locator("img[alt],svg title").evaluate_all("(els)=>els.map(e=>e.getAttribute('alt')||e.textContent||'')"))
                                name = " ".join(v.strip() for v in values if v.strip())
                                if len(name) <= 100 and re.search(r"download|export|print|pdf|electronic file|plain text|text pane", name,re.I):
                                    result.append((pg,ctl,name))
                            except PlaywrightTimeout:
                                continue
                return result
            # The report opens in a new tab; wait for that tab and its toolbar, not the folder.
            for pg in context.pages:
                if pg != page and not pg.is_closed():
                    pg.wait_for_load_state("domcontentloaded", timeout=20000)
                    pg.bring_to_front()
            controls = []
            for _ in range(4):
                guard()
                controls = viewer_controls()
                if controls or downloads or pdf_responses:
                    break
                context.pages[-1].wait_for_timeout(2500)
            print(json.dumps({"viewer_pages":[pg.url for pg in context.pages],"visible_export_controls":sorted(set(x[2] for x in controls))}),flush=True)
            guard()
            if not downloads and not pdf_responses:
                # Use the explicit public toolbar action. Avoid print-only or permission prompts.
                matches = [c for c in controls if re.search(r"download|export|print.*pdf|pdf.*print",c[2],re.I) and not re.search(r"cancel|selected entries|folder|multiple",c[2],re.I)]
                if not matches:
                    matches = [c for c in controls if re.fullmatch(r"(?:view |open )?pdf(?: file)?|print",c[2],re.I)]
                if not matches:
                    # Print only short toolbar labels, never document contents.
                    for pg in context.pages:
                        for fr in pg.frames:
                            labels = fr.locator("button, [role=button], a[title], img[alt], input[type=image]").evaluate_all("(els)=>els.filter(e=>e.getClientRects().length).map(e=>({tag:e.tagName,title:e.title||e.getAttribute('aria-label')||e.getAttribute('alt')||'',id:e.id||''})).filter(x=>x.title||x.id).slice(0,80)")
                            print(json.dumps({"frame":fr.url,"toolbar_metadata":labels}),flush=True)
                    raise RuntimeError("no visible public download/export control; manual export required")
                pg,ctl,name = matches[0]
                print(json.dumps({"chosen_public_control":name}),flush=True)
                ctl.click(timeout=5000)
                pg.wait_for_timeout(2000)
                guard()
                if not downloads and not pdf_responses:
                    controls2 = viewer_controls()
                    print(json.dumps({"dialog_controls":sorted(set(x[2] for x in controls2))}),flush=True)
                    confirm = [c for c in controls2 if re.fullmatch(r"download(?: & print| and print)?(?: download)?",c[2],re.I)]
                    if len(confirm)==1:
                        confirm[0][1].click(timeout=5000)
                        confirm[0][0].wait_for_timeout(2500)
            guard()
            dest=Path(tmp)/"report.pdf"
            if downloads:
                downloads[0].save_as(dest)
            elif pdf_responses:
                dest.write_bytes(pdf_responses[0].body())
            else:
                raise RuntimeError("public viewer did not deliver PDF")
            parsed=verify_pdf(dest)
            if parsed["period_start"]!=report_day.isoformat():
                raise RuntimeError("document period does not match directory label")
            acquired.append({"visible_title":label,"document_url":report_href,**parsed})
            print(json.dumps({"acquired":acquired,"production_writes":0}))
            if not acquired:
                raise RuntimeError("no official report obtained")
            if acquired[0]["sha256"] == "55864c0276a4c958d7fcc0501e8a1c425ce78a9fd26f7b2814e90404ed606295":
                assert acquired[0]["visible_total"] == 34 and acquired[0]["printed_total"] == 35
                assert acquired[0]["candidate_counts"] == {"New single-family dwelling":18,"other":11,"New townhome":3,"New commercial construction":2}
                assert acquired[0]["candidate_valuation"] == 16841106
                print("Exact owner-supplied PDF reconciliation passed; partial evidence only.", flush=True)
        finally:
            browser.close()

if __name__ == "__main__":
    main()
