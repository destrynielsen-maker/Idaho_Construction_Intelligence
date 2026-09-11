from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
import re

from pypdf import PdfReader

from .base import CollectorResult
from .common import discover_links, get
from ..models import Permit


ARCHIVE_URL = "https://kcgov.us/Archive/44"


class KootenaiCountyCollector:
    name = "Kootenai County"
    landing_url = ARCHIVE_URL
    freshness_days = 14

    @staticmethod
    def _report_start(label: str):
        match = re.search(
            r"\b(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(\d{1,2}),\s+(20\d{2})\b",
            label or "",
            re.I,
        )
        if not match:
            return None
        try:
            return datetime.strptime(" ".join(match.groups()), "%B %d %Y").date()
        except ValueError:
            return None

    def _weekly_reports(self):
        links = discover_links(
            ARCHIVE_URL,
            ("WEEKLY BUILDING PERMIT REPORT", "Weekly Building Permit Report"),
        )
        reports = []
        seen_urls = set()
        for label, url in links:
            if "/Archive/ViewFile/Item/" not in url or url in seen_urls:
                continue
            seen_urls.add(url)
            start = self._report_start(label)
            reports.append((start, label, url))
        reports.sort(key=lambda item: (item[0] or date.min, item[1], item[2]), reverse=True)
        return reports

    def collect(self):
        report_links = self._weekly_reports()
        if not report_links:
            return CollectorResult(self.name, ARCHIVE_URL, [], "No weekly archive report links discovered")

        # Pull the latest six unique weekly reports so a temporary missed run does not
        # create a gap. Stable permit keys deduplicate overlaps across reports.
        permits = []
        parsed_reports = []
        seen_permits = set()
        for start, label, url in report_links[:6]:
            response = get(url, referer=ARCHIVE_URL)
            if "pdf" not in response.headers.get("content-type", "").lower() and not response.content.startswith(b"%PDF"):
                continue
            text = _layout_pdf_text(response.content)
            parsed = parse_kootenai(text, url)
            parsed_reports.append(f"{label} ({len(parsed)} parsed)")
            for permit in parsed:
                if permit.key not in seen_permits:
                    permits.append(permit)
                    seen_permits.add(permit.key)

        latest_start, latest_label, latest_url = report_links[0]
        note = "Latest weekly archive reports: " + "; ".join(parsed_reports[:3])
        if latest_start:
            # Kootenai names each report for the Sunday starting the reporting week.
            latest_end = latest_start + timedelta(days=6)
            age = (date.today() - latest_end).days
            note += f". Latest report period {latest_start.isoformat()} through {latest_end.isoformat()} ({age} days old)"
            if age > self.freshness_days:
                note += f" WARNING: newest published Kootenai weekly report is older than {self.freshness_days} days"
        return CollectorResult(self.name, latest_url, permits, note)


def _layout_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text(extraction_mode="layout") or "")
        except TypeError:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _iso_date(value: str) -> str:
    return datetime.strptime(value, "%m/%d/%Y").date().isoformat()


def _money(value: str):
    match = re.search(r"\$([\d,]+(?:\.\d{2})?)", value or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _classification_for(record_type: str, subtype: str, title: str):
    text = re.sub(r"\s+", " ", f"{subtype} {title}").strip().lower()
    if any(token in text for token in ("duplex", "triplex", "fourplex", "multi-family", "multifamily", "apartment", "townhome", "townhouse")):
        return "New Multifamily"
    if "new sfr" in text or "new single" in text or "new one family" in text:
        return "New Single Family"
    if record_type.upper() == "COMMERCIAL BUILDING":
        if any(token in text for token in ("new commercial", "commercial shell", "shell building", "new warehouse", "new office", "new retail", "new industrial")):
            return "Commercial New Construction"
        if re.search(r"\bnew\b.{0,80}\bbuilding\b", text, re.I):
            return "Commercial New Construction"
    return None


def parse_kootenai(text: str, source_url: str) -> list[Permit]:
    """Parse Kootenai's layout-preserved weekly issued-permit PDF rows.

    In layout mode each record is emitted as a permit/detail row followed by an optional
    issue-date/subtype row and then a status/title row. Anchoring on the permit row prevents
    the cross-record number/address leakage produced by broad nearby-text windows.
    """
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    row_re = re.compile(r"^\s*((?:RES|COM)\d{2}-\d{3,5})\s{2,}(RESIDENTIAL BUILDING|COMMERCIAL BUILDING)\s{2,}(.+)$", re.I)
    out = []

    row_indexes = [idx for idx, line in enumerate(lines) if row_re.match(line)]
    for pos, idx in enumerate(row_indexes):
        match = row_re.match(lines[idx])
        if not match:
            continue
        permit_number = match.group(1).upper()
        record_type = match.group(2).upper()

        parts = [part.strip() for part in re.split(r"\s{2,}", lines[idx].strip()) if part.strip()]
        if len(parts) < 5:
            continue
        address = parts[2]
        owner = parts[3] or None
        valuation = _money(parts[4])

        end = row_indexes[pos + 1] if pos + 1 < len(row_indexes) else len(lines)
        block = lines[idx + 1:end]
        issued_raw = ""
        subtype = ""
        contractor = None
        status = ""
        title = ""

        for line in block:
            stripped = line.strip()
            date_match = re.match(r"^(\d{1,2}/\d{1,2}/20\d{2})\s{2,}(.+)$", stripped)
            if date_match and not issued_raw:
                issued_raw = date_match.group(1)
                date_parts = [part.strip() for part in re.split(r"\s{2,}", stripped) if part.strip()]
                if len(date_parts) >= 2:
                    subtype = date_parts[1]
                if len(date_parts) >= 4:
                    contractor = date_parts[3]
                elif len(date_parts) >= 3 and any(word in date_parts[-1].upper() for word in ("CONSTRUCTION", "BUILDERS", "HOMES", "CONTRACTING")):
                    contractor = date_parts[-1]

            title_match = re.search(r"\b(Issued|Finaled|Cancelled)\b\s+Permit Title:\s*(.+)$", stripped, re.I)
            if title_match:
                status = title_match.group(1).title()
                title = title_match.group(2).strip()
                break

        if status != "Issued" or not issued_raw or not title:
            continue

        permit_type = _classification_for(record_type, subtype, title)
        if not permit_type:
            continue

        try:
            issued = _iso_date(issued_raw)
        except ValueError:
            continue

        out.append(Permit(
            state="ID",
            jurisdiction="Kootenai County",
            permit_number=permit_number,
            issued_date=issued,
            permit_type=permit_type,
            address=address,
            source_name="Kootenai County weekly building permit report",
            source_url=source_url,
            project_name=title,
            building_use=subtype or None,
            valuation=valuation,
            contractor=contractor,
            owner=owner,
            status=status,
            raw={
                "record_type": record_type,
                "subtype": subtype,
                "status": status,
                "context": " | ".join(line.strip() for line in [lines[idx], *block] if line.strip()),
            },
        ))

    unique = {}
    for permit in out:
        unique[permit.permit_number] = permit
    return list(unique.values())
