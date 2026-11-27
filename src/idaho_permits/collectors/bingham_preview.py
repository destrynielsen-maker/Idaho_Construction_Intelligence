"""Bingham County official issued-report preview (not registered for production).

The county reuses Record # across different permit titles. Keep title-level
observations under the record number rather than inventing separate permit IDs
or treating the later title as a replacement. Owner is not contractor.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from ..models import Permit

INDEX = "https://www.binghamid.gov/BuildingPermitActivityReports"
REPORT_PREFIX = "/media/Departments/PlanningandDevelopment/Building Permit Activity Reports/"
FIELDS = ("record_number", "title", "issued_date", "address", "valuation")
HEADERS = ("Record #", "Title", "Type", "Date Issued", "Owner Name", "Full Address", "Value")


def official_report_url(url):
    from urllib.parse import unquote
    p = urlparse(url)
    return (p.scheme == "https" and p.netloc == "www.binghamid.gov"
            and unquote(p.path).startswith(REPORT_PREFIX)
            and p.path.lower().endswith(".pdf") and not p.query and not p.fragment)


def read_fixture(path):
    with Path(path).open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("Unexpected reviewed report schema")
        return list(reader)


def parse_layout(text):
    """Prototype for pypdf layout-mode text; require explicit column headers.

    Tested against a reconstructed layout, not original publisher PDF bytes.
    Fail on unknown/wrapped/shifted rows rather than guess date or owner.
    """
    rows = []
    starts = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if all(h in line for h in HEADERS):
            starts = [line.index(h) for h in HEADERS]
            if starts != sorted(starts) or len(set(starts)) != len(starts):
                raise ValueError("Invalid report header")
            continue
        if starts is None:
            raise ValueError("No explicit issued-report header")
        vals = [line[start:end].strip()
                for start, end in zip(starts, starts[1:] + [None])]
        if vals[2] != "Permit/License":
            raise ValueError("Unexpected row type or column shift")
        issued = datetime.strptime(vals[3], "%m/%d/%Y").date().isoformat()
        rows.append(dict(zip(FIELDS, [vals[0], vals[1], issued, vals[5], vals[6]])))
    if not rows:
        raise ValueError("No parsed issued observations")
    return rows


def preview(rows, source_url, report_month, expected_rows):
    if not official_report_url(source_url):
        raise ValueError("Not an authorized Bingham County report URL")
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", report_month):
        raise ValueError("Invalid report month")
    if len(rows) != expected_rows or not rows:
        raise ValueError("Source row count mismatch")
    by_number = defaultdict(list)
    seen = set()
    for index, raw in enumerate(rows, 1):
        if set(raw) != set(FIELDS) or any(v is None for v in raw.values()):
            raise ValueError("Invalid observation schema")
        row = {k: str(v).strip() for k, v in raw.items()}
        number = row["record_number"].upper()
        if not re.fullmatch(r"[A-Z]+-\d{2}-\d+", number):
            raise ValueError("Unrecognized county record number")
        issued = date.fromisoformat(row["issued_date"])
        if issued.isoformat() != row["issued_date"] or issued.isoformat()[:7] != report_month:
            raise ValueError("Issue date not in report month")
        if not row["title"] or not row["address"]:
            raise ValueError("Missing source title or work location")
        value = Decimal(row["valuation"])
        if not value.is_finite() or value < 0:
            raise ValueError("Invalid source valuation")
        identity = (number, row["title"].casefold(), row["issued_date"])
        if identity in seen:
            raise ValueError("Duplicate or conflicting observation")
        seen.add(identity)
        by_number[number].append({
            **row, "record_number": number, "source_row": index,
            "source_url": source_url, "report_month": report_month,
            "stage": "issued", "contractor": None,
            "owner_attribution": "not imported from source owner column",
        })
    groups = {}
    for number, observations in sorted(by_number.items()):
        # A shared number stays one identity, and multiple titles remain visible.
        # No automatic preference for structural vs. floodplain observations.
        dates = {r["issued_date"] for r in observations}
        addresses = {r["address"] for r in observations}
        status = "single_observation" if len(observations) == 1 else "multiple_titles_review"
        if len(dates) != 1 or len(addresses) != 1:
            status = "conflicting_identity_review"
        groups[number] = {
            "jurisdiction": "Bingham County", "permit_number": number,
            "observations": observations, "review_status": status,
            "qualification_status": "not_evaluated",
        }
    return {
        "publication": "disabled", "report_month": report_month,
        "source_url": source_url, "row_count": len(rows),
        "identity_count": len(groups), "groups": groups,
        "latest_issued_date": max(r["issued_date"] for g in groups.values() for r in g["observations"]),
    }


def tracker_preview(group):
    """Only a single-observation group is eligible for a tracker-shaped preview."""
    if group["review_status"] != "single_observation":
        raise ValueError("Shared identity requires review before mapping")
    r = group["observations"][0]
    return Permit(state="ID", jurisdiction="Bingham County",
                  permit_number=group["permit_number"], issued_date=r["issued_date"],
                  permit_type=r["title"], address=r["address"],
                  source_name="Bingham County issued building permit report",
                  source_url=r["source_url"], valuation=float(r["valuation"]),
                  contractor=None, owner=None, stage="PERMITTED", qualifies=False,
                  score=0, raw={"publication_status": "review_only", **group})
