"""Offline issued-permit review only. Not registered with the production pipeline."""
import argparse
import csv
import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from .models import Permit

ISSUERS = {
    "twin_falls_county_id": ("Twin Falls County", {"twinfallscounty.org", "www.twinfallscounty.org"}),
    "caldwell_city_id": ("Caldwell", {"cityofcaldwell.org", "www.cityofcaldwell.org"}),
}
FIELDS = "issuer permit_number issued_date permit_type work_type contractor project_address valuation source_url source_page report_month".split()


def read_batch(path, expected_count):
    """Read a manually reconciled official issued report; never infer a date."""
    path = Path(path)
    raw_bytes = path.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    records = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if len(reader.fieldnames or []) != len(FIELDS) or set(reader.fieldnames or []) != set(FIELDS):
            raise ValueError("Unexpected CSV schema")
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"Invalid CSV row {line}")
            r = {k: v.strip() for k, v in row.items()}
            issuer = r["issuer"]
            number = r["permit_number"].upper()
            url = urlparse(r["source_url"])
            if issuer not in ISSUERS or url.scheme != "https" or url.hostname not in ISSUERS[issuer][1] or url.username or url.password:
                raise ValueError(f"Unapproved issuer/source on line {line}")
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{2,39}", number):
                raise ValueError("Invalid permit number")
            if issuer == "twin_falls_county_id" and not re.fullmatch(r"B\d{4}-\d{4,}", number):
                raise ValueError("Invalid county permit format")
            issued = date.fromisoformat(r["issued_date"])
            if issued.isoformat() != r["issued_date"] or issued.isoformat()[:7] != r["report_month"]:
                raise ValueError("Issue date not in report month")
            if not r["permit_type"] or int(r["source_page"]) < 1:
                raise ValueError("Missing type/page evidence")
            if r["valuation"]:
                valuation = Decimal(r["valuation"])
                if not valuation.is_finite() or valuation < 0:
                    raise ValueError("Invalid valuation")
            key = f"{issuer}:{number}:issued"
            if key in records:
                raise ValueError(f"Duplicate identity: {key}")
            records[key] = {
                **r, "permit_number": number, "event_stage": "issued",
                "identity": key, "source_csv_sha256": digest,
                "source_csv_line": line, "qualification_status": "not_evaluated",
                "publication_status": "review_only",
            }
    if len(records) != expected_count:
        raise ValueError(f"Expected {expected_count}, parsed {len(records)}; stop for review")
    return records


def merge_preview(existing, incoming):
    """Append only, preserve first seen and all prior evidence; quarantine conflicts."""
    result = dict(existing)
    conflicts, added, matched = [], [], []
    for key, row in incoming.items():
        if key not in existing:
            result[key] = row
            added.append(key)
            continue
        old = existing[key]
        changed = [f for f in FIELDS if f not in ("source_page", "source_url", "report_month") and old.get(f) != row.get(f)]
        if changed:
            conflicts.append({"identity": key, "changed_fields": changed, "candidate": row})
        else:
            matched.append(key)
    return {
        "historical_count": len(existing), "candidate_count": len(incoming),
        "preview_count": len(result), "added": added, "matched": matched,
        "conflicts": conflicts, "missing_from_batch_retained": sorted(set(existing) - set(incoming)),
        "records": result, "publication": "disabled",
    }


def tracker_preview(row):
    """Build an unqualified tracker-shaped object. Never pass it to live collection."""
    if row.get("event_stage") != "issued" or row.get("publication_status") != "review_only":
        raise ValueError("Expected reviewed issued candidate")
    return Permit(
        state="ID", jurisdiction=ISSUERS[row["issuer"]][0],
        permit_number=row["permit_number"], issued_date=row["issued_date"],
        permit_type=row["permit_type"], address=row["project_address"],
        source_name="Official county/city issued report (manual review)",
        source_url=row["source_url"], contractor=row["contractor"] or None,
        valuation=float(row["valuation"]) if row["valuation"] else None,
        stage="PERMITTED", qualifies=False, score=0, sales_score=0,
        raw=dict(row),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv")
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--existing", help="Prior offline preview only")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    previous = {}
    if args.existing:
        payload = json.loads(Path(args.existing).read_text(encoding="utf-8"))
        if payload.get("publication") != "disabled" or not isinstance(payload.get("records"), dict):
            raise ValueError("Not an offline preview")
        previous = payload["records"]
    result = merge_preview(previous, read_batch(args.csv, args.expected_count))
    result["tracker_preview"] = [tracker_preview(r).to_dict() for r in result["records"].values()]
    with Path(args.output).open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Review only: {result['preview_count']} records; {len(result['conflicts'])} conflicts")
    if result["conflicts"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
