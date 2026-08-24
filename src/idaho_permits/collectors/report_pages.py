from __future__ import annotations
import re
from .base import CollectorResult
from .common import discover_links,get,pdf_text
from ..models import Permit

class LatestPermitReportCollector:
    def __init__(self,name,landing_url,include): self.name=name; self.landing_url=landing_url; self.include=include
    def collect(self):
        links=discover_links(self.landing_url,self.include)
        pdfs=[(a,u) for a,u in links if '.pdf' in u.lower()]
        if not pdfs: return CollectorResult(self.name,self.landing_url,[],f'No discoverable PDF links matched {self.include}; source remains visible for manual prospecting')
        label,url=pdfs[-1]
        text=pdf_text(get(url).content)
        return CollectorResult(self.name,url,parse_generic(text,self.name,url),f'Latest discovered report: {label}')

def parse_generic(text,jurisdiction,url):
    lines=[re.sub(r'\s+',' ',x).strip() for x in text.splitlines() if x.strip()]
    out=[]
    date_re=re.compile(r'\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](20\d\d)\b')
    permit_re=re.compile(r'\b(?:BLD|BLDG|BP|RES|COM|SFR|MFR)?[- ]?\d{4,}[A-Z0-9-]*\b',re.I)
    for idx,line in enumerate(lines):
        low=line.lower()
        if not any(s in low for s in ('new single','single family dwelling','new commercial','new building','townhome','town home','duplex','multifamily','multi-family','apartment','shell')): continue
        chunk=' | '.join(lines[max(0,idx-3):min(len(lines),idx+4)])
        dm=date_re.search(chunk); pm=permit_re.search(chunk)
        addr=next((x for x in lines[max(0,idx-3):idx+4] if re.search(r'\b\d{1,6}\s+[A-Z0-9].*\b(?:ST|AVE|RD|DR|LN|WAY|CT|BLVD|HWY|PL|PKWY)\b',x,re.I)), '')
        if not (dm and pm and addr): continue
        pno=pm.group(0).strip(); date=dm.group(0)
        if any(p.permit_number==pno for p in out): continue
        out.append(Permit('ID',jurisdiction,pno,date,line,addr,f'{jurisdiction} permit report',url,project_name=line,raw={'context':chunk}))
    return out

MeridianCollector=lambda: LatestPermitReportCollector('Meridian','https://data.meridiancity.org/community-development/building/construction-reports/',('Week','Full Report','Summary Report'))
NampaCollector=lambda: LatestPermitReportCollector('Nampa','https://www.cityofnampa.us/427/Permit-Reports',('08/','August 2026','Permit Activity Type Report'))
