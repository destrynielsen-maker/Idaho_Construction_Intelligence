from __future__ import annotations

import re
from datetime import datetime

from .base import CollectorResult
from .common import discover_links, get, pdf_text
from ..models import Permit


ARCHIVE_URL = "https://kcgov.us/Archive/44"


class KootenaiCountyCollector:
    name = "Kootenai County"
    landing_url = ARCHIVE_URL

    def collect(self):
        links = discover_links(ARCHIVE_URL, ("WEEKLY BUILDING PERMIT REPORT", "Weekly Building Permit Report"))
        report_links = [(label, url) for label, url in links if "/Archive/ViewFile/Item/" in url]
        if not report_links:
            return CollectorResult(self.name, ARCHIVE_URL, [], "No weekly archive report links discovered")

        # Archive is newest-first. Pull the latest six weekly reports so a temporary
        # missed run does not create a gap; stable permit keys deduplicate overlaps.
        permits = []
        parsed_reports = []
        seen = set()
        for label, url in report_links[:6]:
            response = get(url, referer=ARCHIVE_URL)
            if "pdf" not in response.headers.get("content-type", "").lower() and not response.content.startswith(b"%PDF"):
                continue
            text = pdf_text(response.content)
            parsed = parse_kootenai(text, url)
            parsed_reports.append(f"{label} ({len(parsed)} parsed)")
            for permit in parsed:
                if permit.key not in seen:
                    permits.append(permit)
                    seen.add(permit.key)

        note = "Latest weekly archive reports: " + "; ".join(parsed_reports[:3])
        return CollectorResult(self.name, ARCHIVE_URL, permits, note)


def _iso_date(value: str) -> str:
    return datetime.strptime(value, "%m/%d/%Y").date().isoformat()


def parse_kootenai(text: str, source_url: str) -> list[Permit]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    out = []
    permit_re = re.compile(r"\b(?:RES|COM)\d{2}-\d{3,5}\b", re.I)
    date_re = re.compile(r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/20\d{2}\b")
    money_re = re.compile(r"\$([\d,]+(?:\.\d{2})?)")
    address_re = re.compile(r"\b\d{1,6}(?: \[TEMP\])?\s+[A-Z0-9].*\b(?:ST|AVE|RD|DR|LN|WAY|CT|BLVD|HWY|PL|PKWY|CIR|LOOP|ROAD)\b", re.I)

    for idx, line in enumerate(lines):
        if not line.lower().startswith("permit title:"):
            continue
        title = line.split(":", 1)[1].strip()
        low = title.lower()
        if not any(signal in low for signal in (
            "new sfr", "new single", "new one family", "duplex", "fourplex",
            "multi-family", "multifamily", "apartment", "new commercial", "commercial shell", "shell building"
        )):
            continue

        nearby = lines[max(0, idx - 24): min(len(lines), idx + 10)]
        permit_number = next((m.group(0).upper() for x in reversed(nearby) if (m := permit_re.search(x))), None)
        issued = next((m.group(0) for x in reversed(nearby) if (m := date_re.search(x))), None)
        address = next((m.group(0) for x in nearby if (m := address_re.search(x))), "")
        if not permit_number or not issued or not address:
            continue

        valuation = None
        values = []
        for x in nearby:
            for raw in money_re.findall(x):
                try:
                    values.append(float(raw.replace(",", "")))
                except ValueError:
                    pass
        if values:
            valuation = max(values)

        contractor = None
        for x in nearby:
            ux = x.upper()
            if any(tag in ux for tag in (" CONSTRUCTION", " BUILDERS", " HOMES LLC", " CONTRACTING")) and "$" not in x:
                contractor = x
                break

        permit_type = title
        out.append(Permit(
            state="ID",
            jurisdiction="Kootenai County",
            permit_number=permit_number,
            issued_date=_iso_date(issued),
            permit_type=permit_type,
            address=address,
            source_name="Kootenai County weekly building permit report",
            source_url=source_url,
            project_name=title,
            valuation=valuation,
            contractor=contractor,
            raw={"context": " | ".join(nearby)},
        ))

    # A report can repeat a permit title in extraction order; keep one record per permit.
    unique = {}
    for permit in out:
        unique[permit.permit_number] = permit
    return list(unique.values())
