from __future__ import annotations
import re
from datetime import datetime
from .base import CollectorResult
from .common import discover_links,get,pdf_text
from ..models import Permit

class LatestPermitReportCollector:
    def __init__(self,name,landing_url,include): self.name=name; self.landing_url=landing_url; self.include=include
    def collect(self):
        links=discover_links(self.landing_url,self.include)
        candidates=[(a,u) for a,u in links if '.pdf' in u.lower() or '/DocumentCenter/View/' in u]
        if not candidates: return CollectorResult(self.name,self.landing_url,[],f'No discoverable report links matched {self.include}; source remains visible for manual prospecting')
        # Pages are chronological; prefer the last matching report and send a browser-like Referer.
        label,url=candidates[-1]
        response=get(url,referer=self.landing_url)
        ctype=response.headers.get('content-type','').lower()
        if 'pdf' not in ctype and not response.content.startswith(b'%PDF'):
            return CollectorResult(self.name,url,[],f'Latest report link was not a PDF ({label}); source remains visible for manual prospecting')
        text=pdf_text(response.content)
        return CollectorResult(self.name,url,parse_generic(text,self.name,url),f'Latest discovered report: {label}')

def parse_generic(text,jurisdiction,url):
    lines=[re.sub(r'\s+',' ',x).strip() for x in text.splitlines() if x.strip()]
    out=[]
    date_re=re.compile(r'\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](20\d\d)\b')
    permit_re=re.compile(r'\b(?:BLD|BLDG|BP|RES|COM|SFR|MFR)[- ]?[A-Z0-9-]*\d[A-Z0-9-]*\b',re.I)
    address_re=re.compile(r'\b\d{1,6}\s+[A-Z0-9].*\b(?:ST|AVE|RD|DR|LN|WAY|CT|BLVD|HWY|PL|PKWY|CIR|TER)\b',re.I)
    signals=('new single','single family dwelling','new commercial','new building','new residential','townhome','town home','duplex','fourplex','multifamily','multi-family','apartment','shell building','shell')
    for idx,line in enumerate(lines):
        if not any(s in line.lower() for s in signals): continue
        nearby=lines[max(0,idx-8):min(len(lines),idx+9)]
        chunk=' | '.join(nearby)
        dm=date_re.search(chunk); pm=permit_re.search(chunk)
        addr=next((x for x in nearby if address_re.search(x)), '')
        if not (dm and pm and addr): continue
        pno=pm.group(0).strip(); issued=datetime.strptime(dm.group(0).replace('-','/'),'%m/%d/%Y').date().isoformat()
        if any(p.permit_number==pno for p in out): continue
        valuation=None
        money=re.findall(r'\$([\d,]+(?:\.\d{2})?)',chunk)
        if money:
            try: valuation=max(float(x.replace(',','')) for x in money)
            except ValueError: pass
        out.append(Permit('ID',jurisdiction,pno,issued,line,addr,f'{jurisdiction} permit report',url,project_name=line,valuation=valuation,raw={'context':chunk}))
    return out

MeridianCollector=lambda: LatestPermitReportCollector('Meridian','https://data.meridiancity.org/community-development/building/construction-reports/',('Week 1','Week 2','Week 3','Week 4','Full Report','Summary Report'))
NampaCollector=lambda: LatestPermitReportCollector('Nampa','https://www.cityofnampa.us/427/Permit-Reports',('08/03/2026','08/10/2026','08/17/2026','08/24/2026','August 2026'))
