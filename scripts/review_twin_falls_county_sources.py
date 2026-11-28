"""Read-only publisher-PDF validation. No production pipeline calls."""
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
import requests
from pypdf import PdfReader
from idaho_permits.county_intake import read_batch

for month, count, total in [("2026-09", 30, "10,333,504.06"), ("2026-10", 19, "2,420,828.01")]:
    records = read_batch(Path("tests/fixtures") / f"twin_falls_county_{month}.csv", count)
    urls = {r["source_url"] for r in records.values()}
    assert len(urls) == 1
    url = urls.pop()
    response = requests.get(url, timeout=40)
    response.raise_for_status()
    final = urlparse(response.url)
    assert final.scheme == "https" and final.hostname in {"twinfallscounty.org", "www.twinfallscounty.org"}
    assert response.content.startswith(b"%PDF"), "not a PDF"
    pdf = PdfReader(io.BytesIO(response.content))
    observed = []
    pages = []
    for page_index, page in enumerate(pdf.pages, 1):
        normal = page.extract_text() or ""
        layout = page.extract_text(extraction_mode="layout") or ""
        # Reconcile by date-number pairs rather than trusting report filename,
        # page order, or a count of arbitrary permit-shaped strings.
        pattern = r"(\d{1,2}/\d{1,2}/20\d{2})\s+(B\d{4}-\d{4,})\b"
        hits = re.findall(pattern, layout)
        if not hits:
            hits = re.findall(pattern, normal)
        observed.extend((number, datetime.strptime(day, "%m/%d/%Y").date().isoformat(), page_index) for day, number in hits)
        pages.append(normal + "\n" + layout)
    expected = {(r["permit_number"], r["issued_date"], int(r["source_page"])) for r in records.values()}
    actual = set(observed)
    print(json.dumps({"month": month, "url": url, "sha256": hashlib.sha256(response.content).hexdigest(),
        "pages": len(pdf.pages), "expected": len(expected), "observed": len(observed), "missing": sorted(expected-actual),
        "unexpected": sorted(actual-expected), "total_verified": total in "\n".join(pages)}), flush=True)
    assert len(observed) == len(actual) == count and actual == expected, "source row identities or issue dates disagree"
    assert total in "\n".join(pages), "source valuation total not found"
    assert sum(Decimal(r["valuation"] or "0") for r in records.values()) == Decimal(total.replace(",", ""))
print("Both original publisher reports verified against date, ID, page and valuation-total fixtures.")
