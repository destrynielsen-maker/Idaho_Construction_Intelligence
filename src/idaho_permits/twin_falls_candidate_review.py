"""County report to tracker mapping for isolated acceptance review.

Never registered, never writes a store, never changes shared qualification.
A semantic conflict is a release blocker, not an instruction to suppress a lead.
"""
from datetime import date
from decimal import Decimal
import re

from .models import Permit
from .classify import classify_permit
from .twin_falls_county_pdf import official, NUMBER

def to_candidate(row):
    number = row["permit_number"]
    issued = date.fromisoformat(row["issued_date"])
    if not NUMBER.fullmatch(number) or issued.isoformat()[:7] != row["report_month"]:
        raise ValueError("invalid issued identity")
    if issued > date.today() or not official(row["source_url"]):
        raise ValueError("invalid issuance source")
    if not re.fullmatch(r"[a-f0-9]{64}", row["source_pdf_sha256"]) or int(row["source_page"]) < 1:
        raise ValueError("missing PDF evidence")
    val = Decimal(row["valuation_decimal"])
    if not val.is_finite() or val < 0:
        raise ValueError("invalid valuation")
    if not all(row.get(k) for k in ("permit_type", "work_type", "description", "project_address")):
        raise ValueError("missing source fields")
    return Permit(
        state="ID", jurisdiction="Twin Falls County", county="Twin Falls",
        permit_number=number, issued_date=issued.isoformat(),
        permit_type=row["permit_type"], building_use=row["work_type"],
        project_name=row["description"], address=row["project_address"],
        contractor=row.get("contractor") or None, owner=row.get("owner") or None,
        subdivision=row.get("subdivision") or None, apn=row.get("parcel") or None,
        valuation=float(val), stage="PERMITTED",
        source_name="Twin Falls County official monthly issued building permits",
        source_url=row["source_url"], raw=dict(row),
    )

def review_candidates(rows):
    """Apply existing classifier to copies, with explicit review diagnostics."""
    result = {}
    flags = []
    for row in rows:
        p = to_candidate(row)
        if p.key in result:
            raise ValueError("duplicate tracker identity")
        classify_permit(p)
        desc = row["description"].lower()
        # Explicit contradictory work descriptions are evidence to review,
        # not additional qualification rules. Keep the classifier result.
        if p.qualifies and p.classification == "SINGLE_FAMILY" and re.search(r"\b(detached\s+(?:shop|garage)|storage\s+shed|pole\s+barn)\b", desc):
            flags.append({"key": p.key, "source_type": p.permit_type,
                          "description": row["description"], "reason": "residential subtype vs accessory description"})
        result[p.key] = p
    return result, flags
