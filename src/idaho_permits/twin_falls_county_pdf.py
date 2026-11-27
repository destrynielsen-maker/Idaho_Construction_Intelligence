"""Review-only automated Twin Falls County monthly report discovery and extraction.

The official landscape PDF has bottom-aligned dates and permit IDs, and a
fixed 18-column layout. Unknown layouts, missing required fields, duplicate
identities and arithmetic discrepancies fail closed. No production writes.
"""
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from urllib.parse import urljoin, urlparse
import hashlib
import re

import requests
from bs4 import BeautifulSoup

INDEX = "https://twinfallscounty.org/building_department/monthly_permits/"
HOSTS = {"twinfallscounty.org", "www.twinfallscounty.org"}
MONTHS = "January February March April May June July August September October November December".split()
LABEL = re.compile(r"(" + "|".join(MONTHS) + r") (20\d{2})", re.I)
DATE = re.compile(r"\d{1,2}/\d{1,2}/20\d{2}")
NUMBER = re.compile(r"B\d{4}-\d{4,}")
# Column starts are normalized to the official October landscape layout,
# excluding a small tolerance at the left edge of each printed cell.
# Two verified publisher layouts; the September PDF uses narrower leading
# columns than October. Identify by the actual SUBTYPE header, never by month.
OCTOBER_STARTS = [62,149,226,319,418,495,534,593,662,758,834,900,1036,1135,1183,1240,1298,1355]
SEPTEMBER_STARTS = [62,140,210,309,398,484,511,531,613,711,793,860,949,1058,1098,1160,1248,1307]
SCALE = 1533
FIELDS = ["issued_date","permit_number","owner","contractor","contractor_address",
          "block","lot","subdivision","project_address","permit_type","work_type",
          "description","valuation","total_sqft","living_sqft","garage_sqft","patio_sqft","parcel"]
def official(url):
    p = urlparse(url)
    return p.scheme == "https" and p.hostname in HOSTS and not p.username and not p.password

def discover(html, base=INDEX):
    if not official(base):
        raise ValueError("unexpected index origin")
    result = {}
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        match = LABEL.fullmatch(" ".join(a.stripped_strings))
        if not match:
            continue
        url = urljoin(base, a["href"])
        if not official(url) or not urlparse(url).path.lower().endswith(".pdf"):
            continue
        month = date(int(match[2]), MONTHS.index(match[1].title())+1, 1).isoformat()[:7]
        if month in result and result[month] != url:
            raise ValueError("conflicting report links")
        result[month] = url
    if not result:
        raise ValueError("no publisher-linked monthly reports")
    return dict(sorted(result.items(), reverse=True))

def fetch_reports(session=None, limit=2):
    session = session or requests.Session()
    r = session.get(INDEX, timeout=40)
    r.raise_for_status()
    for month,url in list(discover(r.text,r.url).items())[:limit]:
        r = session.get(url, timeout=40)
        r.raise_for_status()
        if not official(r.url) or not r.content.startswith(b"%PDF"):
            raise ValueError("unexpected report destination/content")
        yield month, r.url, r.content

def _layout(words,width):
    markers=[w["x0"]*SCALE/width for w in words if w["text"]=="SUBTYPE"]
    if len(markers)!=1:
        raise ValueError("unknown or ambiguous subtype header")
    x=markers[0]
    if 705<=x<=725:
        return SEPTEMBER_STARTS
    if 750<=x<=770:
        return OCTOBER_STARTS
    raise ValueError(f"unrecognized normalized subtype header position {x:.1f}")

def _col(word,width,starts):
    x=word["x0"]*SCALE/width
    return max((i for i,left in enumerate(starts) if x>=left), default=-1)

def _cell(words):
    # Preserve line breaks separately in the raw evidence; join normal cell text.
    return " ".join(w["text"] for w in sorted(words,key=lambda w:(round(w["top"]/2),w["x0"]))).strip()

def _money(value):
    value=value.replace("$","").replace(",","").strip()
    if value in ("","-"):
        return Decimal(0)
    if not re.fullmatch(r"\d+(?:\.\d{2})?",value):
        raise ValueError("unrecognized valuation cell")
    return Decimal(value)

def _footer_money(value):
    # pdfplumber splits the official October total "$ 2 ,420,828.01"
    # into three words. Normalize only spaces around currency/grouping
    # punctuation, not between arbitrary digit groups or separate amounts.
    value = re.sub(r"^\$\s*", "", value.strip())
    value = re.sub(r"\s*,\s*", ",", value)
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{2})?", value):
        raise ValueError("invalid valuation footer")
    return Decimal(value.replace(",", ""))

def parse_pdf(content, month, url):
    import pdfplumber  # optional review dependency; layout unit tests do not require it
    if not official(url) or not content.startswith(b"%PDF"):
        raise ValueError("unexpected source")
    records={}
    totals=[]
    starts=None
    with pdfplumber.open(BytesIO(content)) as pdf:
        for page_index,page in enumerate(pdf.pages,1):
            if not 1.45 < page.width/page.height < 1.65:
                raise ValueError("unknown report layout")
            words=page.extract_words(x_tolerance=1.5,y_tolerance=2)
            if page_index==1:
                starts=_layout(words,page.width)
            anchors=sorted([w for w in words if _col(w,page.width,starts)==0 and DATE.fullmatch(w["text"])],key=lambda w:w["bottom"])
            ids=[w for w in words if _col(w,page.width,starts)==1 and NUMBER.fullmatch(w["text"])]
            if not anchors or len(anchors)!=len(ids):
                raise ValueError(f"unmatched date/ID anchors on page {page_index}: dates={len(anchors)}, IDs={len(ids)}; date/ID token x positions="+str([(round(w["x0"]*SCALE/page.width,1), _col(w,page.width,starts)) for w in words if DATE.fullmatch(w["text"]) or NUMBER.fullmatch(w["text"])]))
            header=[w for w in words if w["text"] in {"DAT_ISSUED","Parcel","Valuation","SUBTYPE","TYPEOFWO"} and w["bottom"]<anchors[0]["top"]]
            if page_index==1 and not any(w["text"]=="DAT_ISSUED" for w in header):
                raise ValueError("explicit issue-date header missing")
            low=max((w["bottom"] for w in header),default=0)+0.1
            for anchor in anchors:
                bottom=anchor["bottom"]+1.5
                columns=[[] for _ in FIELDS]
                for w in words:
                    c=_col(w,page.width,starts)
                    if c>=0 and low < w["bottom"] <= bottom:
                        columns[c].append(w)
                cells=dict(zip(FIELDS,[_cell(w) for w in columns]))
                issued=datetime.strptime(cells["issued_date"],"%m/%d/%Y").date()
                number=cells["permit_number"]
                if issued.isoformat()[:7]!=month or issued>date.today() or not NUMBER.fullmatch(number) or number in records:
                    raise ValueError("invalid/duplicate issue identity")
                if not all(cells[k] for k in ("project_address","permit_type","work_type","description","parcel")):
                    raise ValueError(f"missing required row evidence: {number}")
                records[number]={**cells,"issued_date":issued.isoformat(),"source_page":page_index,
                    "source_url":url,"report_month":month,"valuation_decimal":str(_money(cells["valuation"])),
                    "source_pdf_sha256":hashlib.sha256(content).hexdigest()}
                low=bottom
            remainder=[w for w in words if low<w["bottom"] and _col(w,page.width,starts)==12]
            if remainder:
                # Keep the exact footer contents in diagnostic output so a
                # changed report can be reviewed without guessing or accepting
                # an incomplete monetary reconciliation.
                footer=_cell(remainder)
                try:
                    totals.append(_footer_money(footer))
                except ValueError as exc:
                    raise ValueError(f"unrecognized valuation footer on page {page_index}: {footer!r}; normalized positions="+str([(round(w["x0"]*SCALE/page.width,1),round(w["bottom"],1)) for w in remainder])) from exc
    if not records or len(totals)!=1 or totals[0]!=sum(Decimal(r["valuation_decimal"]) for r in records.values()):
        raise ValueError("missing or unreconciled report valuation total")
    return records
