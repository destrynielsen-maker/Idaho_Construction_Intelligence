from __future__ import annotations
import re
from .base import CollectorResult
from .common import get,pdf_text
from ..models import Permit

class CoeurDAleneCollector:
    name='Coeur d\'Alene'
    pdf_url='https://building.cdaid.org/Reports/IssuedPermitsLastWeek'
    def collect(self):
        text=pdf_text(get(self.pdf_url).content)
        permits=parse(text,self.pdf_url)
        return CollectorResult(self.name,self.pdf_url,permits,'Official issued-permits last-week PDF')

def money(v):
    if not v: return None
    try: return float(v.replace('$','').replace(',',''))
    except: return None

def parse(text,source_url):
    lines=[re.sub(r'\s+',' ',x).strip() for x in text.splitlines() if x.strip()]
    out=[]; i=0
    while i < len(lines):
        if lines[i].startswith('Address:') and ' Project:' in lines[i]:
            m=re.match(r'Address:\s*(.*?)\s+Project:\s*(.*)',lines[i])
            if not m: i+=1; continue
            address,project=m.groups(); permit_no=''; owner=''; issued=''; valuation=None; typ=''; contractor=None; architect=None
            for j in range(i+1,min(i+9,len(lines))):
                if re.match(r'^\d{5,6}-[A-Z0-9]+$',lines[j]):
                    permit_no=lines[j]
                    if j+1 < len(lines):
                        row=lines[j+1]
                        dm=re.search(r'(\d{2}/\d{2}/\d{4})',row)
                        if dm:
                            issued=dm.group(1); owner=row[:dm.start()].strip()
                            tail=row[dm.end():].strip(); vm=re.search(r'(\$[\d,]+(?:\.\d+)?)',tail)
                            if vm: valuation=money(vm.group(1)); typ=(tail[vm.end():].strip() or '')
                            else: typ=tail
                    for k in range(j+2,min(j+7,len(lines))):
                        if lines[k].startswith('Contractor:'): contractor=lines[k].split(':',1)[1].strip()
                        if lines[k].startswith(('Architect:','Draftsman:')) and not architect: architect=lines[k].split(':',1)[1].strip()
                        if lines[k].startswith('Permit Num:') or lines[k].startswith('Address:'): break
                    break
            if permit_no:
                out.append(Permit('ID',"Coeur d'Alene",permit_no,issued,typ,address,"Coeur d'Alene Issued Permits",source_url,project_name=project,valuation=valuation,contractor=contractor,owner=owner,architect=architect,raw={'project':project}))
        i+=1
    return out
