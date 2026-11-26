"""Standalone official City of Blackfoot issued-permit research preview.

Never calls the pipeline or writes history, dashboard outputs, or feeds.
All extracted residential candidates remain unqualified pending human review.
"""
from __future__ import annotations

import calendar
from collections import Counter
from datetime import date, datetime
from io import BytesIO
import json
import re
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

INDEX = "https://www.cityofblackfoot.org/461/Monthly-Building-Permit-Reports"
HOST = "www.cityofblackfoot.org"
DOCUMENT = re.compile(r"/DocumentCenter/View/\d+/Building-Permit-Report-[A-Za-z]+-\d{4}")
LABEL = re.compile(r"Building Permit Report ([A-Za-z]+) (\d{4})", re.I)
MONTHS = {name.casefold(): number for number, name in enumerate(calendar.month_name) if number}
NUMBER = re.compile(r"(?:RES|COMM|MFG)-\d{2}-\d+", re.I)
DATE_CELL = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
EXCLUDE = re.compile(
    r"\b(?:existing|replacement|relocat\w*|remodel\w*|alter\w*|repair\w*|addition|"
    r"accessory|adu|shed|detached garage|reroo\w*|public works|manufactured|mobile home)\b", re.I
)
STICK_HOUSE = re.compile(r"\bstick[ -]built house\b|\bnew single[ -]family\b", re.I)
TWIN_HOME = re.compile(r"\btwin[ -]home\b", re.I)
SIZE_LIMIT = 2_000_000
FRESHNESS_DAYS = 45


def _url(href):
    candidate = urljoin(INDEX, href)
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or parsed.netloc != HOST or parsed.query or parsed.fragment:
        return None
    return candidate if DOCUMENT.fullmatch(parsed.path) else None


def discover(html, today):
    links = {}
    for tag in BeautifulSoup(html, "html.parser").select("a[href]"):
        label = LABEL.fullmatch(tag.get_text(" ", strip=True))
        if not label:
            continue
        month = MONTHS.get(label[1].casefold())
        if not month:
            continue
        period = date(int(label[2]), month, 1)
        if period > today:
            continue
        url = _url(tag["href"])
        if not url:
            continue
        path_label = urlparse(url).path.rsplit("/", 1)[-1]
        if path_label.casefold() != f"Building-Permit-Report-{label[1]}-{label[2]}".casefold():
            raise ValueError("Blackfoot archive link's month disagrees with published label")
        if period in links and links[period] != url:
            raise ValueError("Blackfoot archive contains conflicting links for one month")
        links[period] = url
    if not links:
        raise ValueError("Blackfoot archive has no recognized monthly reports")
    return sorted(links.items(), reverse=True)[:2]


def _get(session, url):
    with session.get(url, timeout=30, allow_redirects=False, stream=True) as response:
        response.raise_for_status()
        if response.status_code != 200 or response.url != url:
            raise ValueError("Unexpected Blackfoot public source response or redirect")
        data = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            data.extend(chunk)
            if len(data) > SIZE_LIMIT:
                raise ValueError("Blackfoot source exceeded size limit")
        return bytes(data)


def parse_rows(text, rows, period, today, source_url, page_number):
    header = " ".join(text.casefold().split())
    if not all(token in header for token in ("record #", "record type", "applicant name", "address", "permit issued", "description")):
        raise ValueError("Unknown Blackfoot report headers")
    # Report has a separate geometric body table; detect date-column
    # position across every row rather than using the PDF's city filename alone.
    if not rows or any(len(row) != 7 for row in rows):
        raise ValueError("Unrecognized Blackfoot table body or width")
    date_positions = []
    for row in rows:
        dates = [i for i in (4, 6) if DATE_CELL.fullmatch((row[i] or "").strip())]
        if len(dates) != 1:
            raise ValueError("Blackfoot row lacks an unambiguous issued-date column")
        date_positions.append(dates[0])
    if len(set(date_positions)) != 1:
        raise ValueError("Blackfoot report mixed incompatible table layouts")
    dt_col = date_positions[0]
    if dt_col == 4 and "permit issued description sq ft" in header:
        desc_col, size_col = 5, 6
    elif dt_col == 6 and "description square feet date" in header:
        desc_col, size_col = 4, 5
    else:
        raise ValueError("Blackfoot issued date column disagrees with header layout")
    outcomes = []
    for row in rows:
        number = (row[0] or "").strip().upper()
        record_type = " ".join((row[1] or "").split()).casefold()
        if not NUMBER.fullmatch(number):
            raise ValueError("Unrecognized Blackfoot permit identity")
        if int(number.split("-")[1]) != period.year % 100:
            raise ValueError("Blackfoot permit ID year conflicts with report period")
        issued = datetime.strptime(row[dt_col].strip(), "%m/%d/%Y").date()
        if (issued.year, issued.month) != (period.year, period.month) or issued > today:
            raise ValueError("Blackfoot permit issue date is outside report month or in future")
        # Applicant and address are deliberately never taken from columns 2/3.
        desc = " ".join((row[desc_col] or "").split())
        if not desc:
            raise ValueError("Blackfoot report row has no description")
        out = {"number": number, "issued_date": issued.isoformat(), "candidate": None}
        if number.startswith("RES-") and record_type == "residential building permit" and not EXCLUDE.search(desc):
            kind = "twin_home_configuration_unverified" if TWIN_HOME.search(desc) else (
                "detached_home_candidate" if STICK_HOUSE.search(desc) else None
            )
            if kind:
                size = re.sub(r"[,\s]", "", row[size_col] or "")
                out["candidate"] = {
                    "jurisdiction": "Blackfoot",
                    "reported_type": kind,
                    "reported_square_feet": int(size) if size.isdigit() else None,
                    "units": None,
                    "contractor": None,
                    "contractor_role": "not_reported_as_contractor",
                    "qualifies": False,
                    "status": "manual_review_only",
                    "evidence_url": f"{source_url}#page={page_number}",
                }
        outcomes.append(out)
    return outcomes


def parse_pdf(data, period, today, source_url):
    # Optional import: the existing pipeline does not use the preview dependency.
    import pdfplumber

    if not data.startswith(b"%PDF-"):
        raise ValueError("Blackfoot published item is not a PDF")
    rows = []
    with pdfplumber.open(BytesIO(data)) as pdf:
        if not 1 <= len(pdf.pages) <= 20:
            raise ValueError("Blackfoot PDF has unexpected page count")
        for i, page in enumerate(pdf.pages, 1):
            table_list = page.extract_tables()
            if len(table_list) != 1:
                raise ValueError("Expected exactly one Blackfoot report table per page")
            rows.extend(parse_rows(page.extract_text(layout=True) or "", table_list[0], period, today, source_url, i))
    return rows


def build_preview(session=None, today=None):
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": "ScoutPermitPreview/1.0 (+public source review only)"})
    today = today or datetime.now(ZoneInfo("America/Boise")).date()
    reports = discover(_get(session, INDEX).decode("utf-8"), today)
    results, all_rows = [], {}
    for period, url in reports:
        rows = parse_pdf(_get(session, url), period, today, url)
        for row in rows:
            old = all_rows.setdefault(row["number"], row)
            if old != row:
                raise ValueError("Conflicting duplicate Blackfoot permit")
        results.append({
            "period": period.isoformat()[:7], "url": url,
            "official_records": len(rows), "candidate_records": sum(bool(r["candidate"]) for r in rows),
        })
    candidates = [
        {"permit_number": n, "issued_date": r["issued_date"], **r["candidate"]}
        for n, r in sorted(all_rows.items()) if r["candidate"]
    ]
    latest = max(row["issued_date"] for row in all_rows.values())
    age = (today - date.fromisoformat(latest)).days
    return {
        "source": INDEX, "source_mode": "standalone_preview_only", "production_writes": 0,
        "new_leads_promoted": 0, "official_records_seen": len(all_rows),
        "reports": results, "candidate_count": len(candidates), "candidates": candidates,
        "candidate_types": dict(Counter(row["reported_type"] for row in candidates)),
        "latest_official_issue": latest, "days_since_latest_official_issue": age,
        "freshness": "fresh" if age <= FRESHNESS_DAYS else "stale",
    }


if __name__ == "__main__":
    print(json.dumps(build_preview(), indent=2))
