"""Review-only City of Twin Falls issued permit intake. Never registered in main."""
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

SOURCE = "https://www.tfid.org/Archive/ViewFile/Item/3493"
ISSUER = "ID:TWIN FALLS CITY"
TYPES = (
    "Commercial Addition", "Commercial Remodel", "Commercial Tenant Improvement",
    "Detached (shed, garage, deck, pool)", "Single-family Residential (detached)",
    "Addition Enclose-Addit., Garage, Sunroom", "Residential Remodel",
    "Duplex (2-family dwelling on one lot)",
    "Multi-Family", "Townhouse (3+ single family attached)",
)
FIELDS = ("source_page", "permit_number", "permit_type", "application_date",
          "issued_date", "project_address", "contractor_field", "valuation", "parent_marker")


def validate_rows(rows, start, end, expected, source=SOURCE, evidence_hash=None):
    """Fail closed on count, type, dates, identity or source inconsistencies."""
    if not source.startswith("https://www.tfid.org/Archive/ViewFile/Item/") or not re.fullmatch(
        r"https://www\.tfid\.org/Archive/ViewFile/Item/\d+", source
    ):
        raise ValueError("Expected official city archive URL")
    if start >= end:
        raise ValueError("Invalid reporting bounds")
    records = {}
    for raw in rows:
        if set(raw) != set(FIELDS) or any(v is None for v in raw.values()):
            raise ValueError("Invalid row schema")
        row = {k: str(v).strip() for k, v in raw.items()}
        n = row["permit_number"]
        if not re.fullmatch(r"\d{2}-\d{4,6}", n) or row["permit_type"] not in TYPES:
            raise ValueError("Unexpected permit identity/type")
        issued = date.fromisoformat(row["issued_date"])
        applied = date.fromisoformat(row["application_date"])
        if not start <= issued < end or applied > issued:
            raise ValueError("Inconsistent issue/application date")
        if not row["project_address"] or int(row["source_page"]) < 1:
            raise ValueError("Missing project address/page")
        if row["parent_marker"] not in {"0", "1"}:
            raise ValueError("Invalid parent marker")
        value = Decimal(row["valuation"])
        if not value.is_finite() or value < 0:
            raise ValueError("Invalid valuation")
        key = ISSUER + ":" + n + ":ISSUED"
        if key in records:
            raise ValueError("Duplicate city permit ID")
        contractor = row["contractor_field"]
        if not contractor or contractor.upper() in {"OWNER/BUILDER", "OWNER-BUILDER", "TBD", "UNKNOWN", "NONE"}:
            contractor = None
        records[key] = {
            **row, "issuer": ISSUER, "identity": key, "source_url": source,
            "stage": "issued", "contractor": contractor, "owner": None,
            "publication": "review_only", "qualification": "not_evaluated",
            "source_evidence_sha256": evidence_hash,
            "relationship_review_required": row["parent_marker"] == "1" or row["permit_type"] in {TYPES[7], TYPES[8], TYPES[9]},
        }
    actual = Counter(r["permit_type"] for r in records.values())
    if actual != Counter(expected):
        raise ValueError(f"Report section counts disagree: {actual!r}")
    return records


def read_review_csv(path, start, end, expected, source=SOURCE):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if len(reader.fieldnames or []) != len(FIELDS) or set(reader.fieldnames or []) != set(FIELDS):
            raise ValueError("Unexpected CSV headers")
        return validate_rows(reader, start, end, expected, source, digest)


def parse_layout_pages(pages):
    """Prototype for pypdf layout text. Validate against actual PDF bytes before use.

    Row labels and section subtotals are mandatory; unrecognized layout fails closed.
    No network calls and no owner/mailing address collection.
    """
    rows, counts = [], Counter()
    active = None
    def finish():
        nonlocal active
        if active is not None:
            raw = active.pop("_description", "")
            active["parent_marker"] = "1" if re.search(r"\bParent\b", raw, re.I) else "0"
            active.pop("_contractor_column", None)
            if set(active) != set(FIELDS):
                raise ValueError("Incomplete permit block")
            rows.append(active)
            active = None
    current_type = None
    for i, page in enumerate(pages, 1):
        if "Permit List" not in page:
            raise ValueError("Unrecognized PDF page")
        for line in page.splitlines():
            m = re.search(r"Permit\s*#:\s*(\d{2}-\d{4,6})\s+(.+?)\s+Application Date:\s*(\d{1,2}/\d{1,2}/\d{4})\s+Issued Date:\s*(\d{1,2}/\d{1,2}/\d{4})", line)
            if m:
                finish()
                n, kind, applied, issued = m.groups()
                current_type = kind.strip()
                active = {"source_page":str(i), "permit_number":n,
                          "permit_type":current_type,
                          "application_date":datetime.strptime(applied,"%m/%d/%Y").date().isoformat(),
                          "issued_date":datetime.strptime(issued,"%m/%d/%Y").date().isoformat()}
                continue
            if "Permit #:" in line:
                raise ValueError("Unrecognized permit header")
            subtotal = re.search(r"Total # of Permits:\s*(\d+)", line)
            if subtotal:
                finish()
                if current_type is None:
                    raise ValueError("Subtotal without section evidence")
                counts[current_type] += int(subtotal.group(1))
                continue
            if active is None:
                continue
            address = re.search(r"Permit Address:\s*(.+?)(?:\s{2,}Valuation:|$)", line)
            if address:
                active["project_address"] = address.group(1).strip()
            value = re.search(r"Valuation:\s*\$?([\d,]+\.\d{2})", line)
            if value:
                active["valuation"] = value.group(1).replace(",","")
            contractor = re.search(r"Contractor:\s*(.*)$", line)
            if contractor:
                active["contractor_field"] = contractor.group(1).strip()
                active["_contractor_column"] = contractor.start()
                continue
            description = re.search(r"Description of Work:\s*(.*)$", line)
            if description:
                active["_description"] = description.group(1).strip()
                active.pop("_contractor_column", None)
                continue
            col = active.get("_contractor_column")
            if col is not None and len(line) > col and line[col:].strip():
                active["contractor_field"] += " " + line[col:].strip()
            elif "_description" in active and re.search(r"^\s{20,}Parent\s*$", line, re.I):
                active["_description"] += " Parent"
        finish()
    if not counts or sum(counts.values()) != len(rows):
        raise ValueError("PDF report subtotals do not reconcile")
    return rows, counts


def read_pdf_preview(path, start, end, expected, source=SOURCE):
    from pypdf import PdfReader
    data = Path(path).read_bytes()
    if not data.startswith(b"%PDF"):
        raise ValueError("Expected PDF bytes")
    reader = PdfReader(path)
    pages = [p.extract_text(extraction_mode="layout") for p in reader.pages]
    rows, totals = parse_layout_pages(pages)
    if totals != Counter(expected):
        raise ValueError("PDF totals differ from independently reviewed counts")
    return validate_rows(rows, start, end, expected, source, hashlib.sha256(data).hexdigest())


def merge_review(existing, incoming):
    """Preserve previous identities and facts; conflicts do not overwrite history."""
    output = dict(existing)
    conflicts = []
    for key, row in incoming.items():
        if key not in output:
            output[key] = row
        elif any(output[key].get(f) != row.get(f) for f in FIELDS if f != "source_page"):
            conflicts.append(key)
    return output, conflicts
