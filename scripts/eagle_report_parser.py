"""Parse the official Eagle weekly permit report's ruled table, not free text.
Owner names are deliberately omitted. A count mismatch remains partial evidence.
"""
import hashlib
import re
from datetime import datetime
from pathlib import Path
import pdfplumber

HEADER = ('Parcel #','Permit #','Issue Date','Parcel Address','Subdivision','Living Area','Contractor','Owner Name','Value of Improve','Description','Permit Type2','Use Class')
COLS = (0,1,2,4,7,8,13,14,15,16,17,18)

def clean(s):
    return ' '.join((s or '').split())

def dt(s):
    return datetime.strptime(clean(s), '%m/%d/%Y').date().isoformat()

def integer(s):
    s = re.sub(r'[,\s]', '', s or '')
    if not re.fullmatch(r'\d+', s):
        raise ValueError('invalid numeric report field')
    return int(s)

def parse_report(path):
    data = Path(path).read_bytes()
    if not data.startswith(b'%PDF-') or not 1 <= len(data) <= 100_000_000:
        raise ValueError('invalid PDF')
    records, ids, totals = [], set(), []
    with pdfplumber.open(path) as doc:
        if not 1 <= len(doc.pages) <= 100:
            raise ValueError('unexpected page count')
        heading=doc.pages[0].extract_text() or ''
        m=re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})',heading)
        if not m:
            raise ValueError('missing issue report period')
        lo, hi = map(dt,m.groups())
        if lo > hi or (datetime.fromisoformat(hi)-datetime.fromisoformat(lo)).days > 7:
            raise ValueError('unexpected reporting period')
        for n, pg in enumerate(doc.pages,1):
            footer=re.findall(r'Page:\s*(\d+)\s+of\s+(\d+)',pg.extract_text() or '',re.I)
            if len(footer)!=1 or tuple(map(int,footer[0]))!=(n,len(doc.pages)):
                raise ValueError('missing or inconsistent report page numbering')
            table=pg.extract_table()
            if not table or any(len(r)!=19 for r in table):
                raise ValueError('unexpected ruled table layout')
            if n==1:
                actual=tuple(clean(table[0][i]).replace('Descriptio n','Description') for i in COLS)
                if actual!=HEADER:
                    raise ValueError('unexpected issue report columns: '+repr(actual))
            for r in table:
                r=[clean(x) for x in r]
                if r[1]=='Permit #':
                    continue
                if not any(r):
                    continue
                if re.fullmatch(r'Total Records:\s*\d+',r[0]):
                    totals.append(int(re.search(r'\d+',r[0]).group()))
                    continue
                if not re.fullmatch(r'\d{4,12}',r[1]):
                    raise ValueError('unrecognized nonempty report row')
                permit_id=r[1]; issue=dt(r[2])
                if permit_id in ids or not lo<=issue<=hi or not r[4]:
                    raise ValueError('duplicate, missing address or date out of period')
                ids.add(permit_id)
                description,ptype,use=r[16:19]
                kind=None
                if (ptype,use) in {('Building Residenti','New Home-'),('Building Residential','New Home Single')}:
                    if description=='New Home': kind='New single-family dwelling'
                    elif description=='New Townhome' and use=='New Home-': kind='New townhome'
                elif (ptype,use) in {('Building Commer','New Commerc'),('Building Commercial','New Commerci')}:
                    if description in ('New Commercial','Core & shell construction'): kind='New commercial construction'
                records.append(dict(permit_number=permit_id,issued_date=issue,address=r[4],subdivision=r[7],apn=r[0] or None,contractor=r[13] or None,valuation=integer(r[15]),living_area_sqft=integer(r[8]),description=description,report_type=ptype,use_class=use,candidate_type=kind,source_page=n))
        if len(totals)>1 or (totals and totals[0]<len(ids)) or not ids:
            raise ValueError(f'invalid printed record total: controls={totals}, visible={len(ids)}')
        total=totals[0] if totals else None
    return dict(sha256=hashlib.sha256(data).hexdigest(),period_start=lo,period_end=hi,printed_total=total,visible_total=len(ids),complete=total is not None and total==len(ids),records=records)
