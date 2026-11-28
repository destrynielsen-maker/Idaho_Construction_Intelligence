"""Acquire official Eagle weekly PDFs through the normal public WebLink UI.

Read-only. Stop on access restrictions, login, robot challenge or robots denial.
No guessed document IDs, private API calls, tracker writes or publication.
"""
import hashlib
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

HOST = "lf.cityofeagle.org"
ROOT = "https://" + HOST
FOLDER = ROOT + "/WebLink/Browse.aspx?id=757930&dbid=0&repo=CityofEagle"
PUBLIC_ENTRY = ROOT + "/WebLink/?dbid=0&repo=CityofEagle"
UA = "EaglePermitReportResearch"
RESTRICT = re.compile(r"verify (?:that )?you(?:'re| are) not a robot|human verification|captcha|access denied|sign in to continue|login required|authentication required", re.I)
REPORT = re.compile(r"(?:11[./_-](?:09|9|13|16|20|23|27)[./_-](?:2026|26)|nov(?:ember)?\s+(?:9|13|16|20|23|27)\b)", re.I)

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

def verify_pdf(path):
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-") or len(raw) > 100_000_000:
        raise RuntimeError("not a bounded PDF")
    import subprocess
    result = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True,
                            text=True, check=True, timeout=30)
    s = result.stdout
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "text_chars": len(s), "issue_label_present": bool(re.search(r"(?:issue[d]?\s+date|date\s+issued)", s, re.I)),
            "permit_label_present": bool(re.search(r"permit\s*(?:#|number|no\b)", s, re.I)),
            "contractor_label_present": bool(re.search(r"contractor", s, re.I)),
            "printed_totals": re.findall(r"(?:total(?:\s+records|\s+permits)?|record count)\s*[:=]?\s*(\d+)", s, re.I)[:10]}

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
            for fr in page.frames:
                body = fr.locator("body").inner_text(timeout=3000)
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
            page.goto(FOLDER, wait_until="domcontentloaded", timeout=30000)
            # Allow the ordinary public UI to render; no repeated requests.
            page.wait_for_timeout(3500)
            guard()
            found = entries()
            print(json.dumps({"public_folder":page.url,"report_labels":sorted(set(x[0] for x in found))}))
            if not found:
                raise RuntimeError("no dated November reports visible in normal folder view")
            # Select a single visible document for each distinct period, newest first.
            selected = []
            for label, item in found:
                if any(label == x[0] for x in selected):
                    continue
                selected.append((label,item))
            acquired = []
            # The download is initiated through the visible public link only.
            # If it opens a document viewer, stop rather than guessing a download endpoint.
            for label,item in selected[:1]:
                try:
                    with page.expect_download(timeout=10000) as dl:
                        item.click(timeout=5000)
                    guard()
                    dest=Path(tmp)/"report.pdf"
                    dl.value.save_as(dest)
                    acquired.append({"visible_title":label,**verify_pdf(dest)})
                except PlaywrightTimeout:
                    guard()
                    # A viewer may expose a clearly labelled Download button.
                    buttons = []
                    for fr in page.frames:
                        buttons.extend([b for b in fr.get_by_role("button", name=re.compile(r"^Download(?: document| PDF)?$",re.I)).all() if b.is_visible()])
                        buttons.extend([b for b in fr.get_by_role("link", name=re.compile(r"^Download(?: document| PDF)?$",re.I)).all() if b.is_visible()])
                    if len(buttons) != 1:
                        raise RuntimeError("public document viewer has no unique visible download control")
                    with page.expect_download(timeout=12000) as dl:
                        buttons[0].click(timeout=5000)
                    guard()
                    dest=Path(tmp)/"report.pdf"
                    dl.value.save_as(dest)
                    acquired.append({"visible_title":label,**verify_pdf(dest)})
            print(json.dumps({"acquired":acquired,"production_writes":0}))
            if not acquired or not all(x["issue_label_present"] and x["permit_label_present"] for x in acquired):
                raise RuntimeError("PDF issue-date and permit identity labels not yet established")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
