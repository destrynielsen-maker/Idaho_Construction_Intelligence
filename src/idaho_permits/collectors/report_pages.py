from __future__ import annotations
import re
from datetime import date,datetime
import requests
from .base import CollectorResult
from .common import discover_links,get,pdf_text
from ..models import Permit

class LatestPermitReportCollector:
    def __init__(self,name,landing_url,include):
        self.name=name; self.landing_url=landing_url; self.include=include

    def collect(self):
        links=discover_links(self.landing_url,self.include)
        candidates=[(a,u) for a,u in links if '.pdf' in u.lower() or '/DocumentCenter/View/' in u]
        if not candidates:
            return CollectorResult(self.name,self.landing_url,[],f'No discoverable report links matched {self.include}; source remains visible for manual prospecting')
        label,url=candidates[-1]
        response=get(url,referer=self.landing_url)
        ctype=response.headers.get('content-type','').lower()
        if 'pdf' not in ctype and not response.content.startswith(b'%PDF'):
            return CollectorResult(self.name,url,[],f'Latest report link was not a PDF ({label}); source remains visible for manual prospecting')
        text=pdf_text(response.content)
        return CollectorResult(self.name,url,parse_generic(text,self.name,url),f'Latest discovered report: {label}')

class MeridianDirectCollector:
    """Collect Meridian's public weekly construction reports.

    Meridian's HTML report landing page is protected by Cloudflare and returns HTTP 403 to
    GitHub-hosted Actions runners. The report PDFs themselves remain public. Try normal
    discovery first, then fall back to direct City-hosted weekly report assets. The fallback
    note includes an explicit age check so a stale direct-report set cannot look silently current.
    """
    name='Meridian'
    landing_url='https://data.meridiancity.org/community-development/building/construction-reports/'
    include=('Week 1','Week 2','Week 3','Week 4','Full Report','Summary Report')
    seed_freshness_days=14
    seed_reports=(
        ('2026-08-10 through 2026-08-16','https://data.meridiancity.org/media/0jycsh0b/weekly-reports-8102026-8162026.pdf'),
        ('2026-08-17 through 2026-08-23','https://data.meridiancity.org/media/uhklc3xc/weekly-reports-8172026-8232026.pdf'),
        ('2026-08-24 through 2026-08-30','https://data.meridiancity.org/media/ln5hcyb5/weekly-reports-8242026-8302026.pdf'),
        ('2026-08-31 through 2026-09-06','https://data.meridiancity.org/media/gx5ghq1k/weekly-report-8-31-thru-9-6.pdf'),
    )

    @staticmethod
    def _report_end(label):
        dates=re.findall(r'\b20\d{2}-\d{2}-\d{2}\b',label or '')
        if not dates: return None
        try: return datetime.strptime(dates[-1],'%Y-%m-%d').date()
        except ValueError: return None

    def collect(self):
        candidates=[]
        discovery_note=''
        try:
            links=discover_links(self.landing_url,self.include)
            candidates=[(a,u) for a,u in links if '.pdf' in u.lower()]
        except requests.RequestException as exc:
            discovery_note=f'Landing-page discovery unavailable ({type(exc).__name__}); '

        merged=[]; seen=set()
        for label,url in [*candidates,*self.seed_reports]:
            if url not in seen:
                seen.add(url); merged.append((label,url))

        permits=[]; fetched=[]; failures=[]
        for label,url in merged:
            try:
                response=get(url,referer=self.landing_url)
                ctype=response.headers.get('content-type','').lower()
                if 'pdf' not in ctype and not response.content.startswith(b'%PDF'):
                    failures.append(f'{label}: not PDF')
                    continue
                parsed=parse_meridian(pdf_text(response.content),self.name,url)
                permits.extend(parsed); fetched.append(f'{label} ({len(parsed)} parsed)')
            except Exception as exc:
                failures.append(f'{label}: {type(exc).__name__}')

        unique={p.key:p for p in permits}
        note=discovery_note + ('Direct/discovered reports: ' + '; '.join(fetched) if fetched else 'No report assets fetched')
        if not candidates:
            ends=[self._report_end(label) for label,_ in self.seed_reports]
            ends=[x for x in ends if x]
            if ends:
                newest=max(ends); age=(date.today()-newest).days
                note += f'. Direct fallback newest report ends {newest.isoformat()} ({age} days old)'
                if age > self.seed_freshness_days:
                    note += f' WARNING: fallback report set is older than {self.seed_freshness_days} days and should be refreshed'
        if failures: note += '. Failures: ' + '; '.join(failures[:4])
        source_url=merged[-1][1] if merged else self.landing_url
        return CollectorResult(self.name,source_url,list(unique.values()),note)

def parse_meridian(text,jurisdiction,url):
    """Parse Meridian's tokenized PDF extraction by permit block.

    pypdf emits labels and values on separate lines (``Permit #`` then the number, ``Issued:``
    then the date, etc.). Report section headings are recognized only at report boundaries, so
    words such as ``RESIDENTIAL`` inside a project description cannot change the active section.
    """
    lines=[re.sub(r'\s+',' ',x).strip() for x in text.splitlines() if x.strip()]
    out=[]
    current_category=''
    current_subtype=''
    section_at={}
    permit_seen=False

    for i,line in enumerate(lines):
        upper=line.upper()
        is_category=upper in {'COMMERCIAL','RESIDENTIAL'}
        boundary_before=(not permit_seen) or (i>0 and lines[i-1].upper()=='PERMITS') or any(
            x.upper()=='BUILDING PERMITS FOR THE WEEK' for x in lines[max(0,i-4):i]
        )
        if is_category and boundary_before and i+1 < len(lines):
            current_category=upper
            current_subtype=lines[i+1].strip()
            section_at[i]=(current_category,current_subtype)
        if line.lower()=='permit #':
            permit_seen=True

    heading_indexes=set(section_at)
    category=''; subtype=''
    for i,line in enumerate(lines):
        if i in section_at:
            category,subtype=section_at[i]
            continue
        if line.lower()!='permit #':
            continue
        if i+1 >= len(lines):
            continue
        pno=lines[i+1].strip()
        if not re.fullmatch(r'[A-Z0-9-]*\d[A-Z0-9-]*',pno,re.I):
            continue

        end=len(lines)
        for j in range(i+2,len(lines)):
            if lines[j].lower()=='permit #' or j in heading_indexes:
                end=j
                break
        block=lines[i:end]
        block_text=' | '.join(block)
        subtype_lower=(subtype or '').lower()
        if 'new' not in subtype_lower and 'shell' not in subtype_lower:
            continue

        def after(label):
            target=label.lower()
            for pos,value in enumerate(block[:-1]):
                if value.lower()==target:
                    return block[pos+1].strip()
            return ''

        issued_raw=after('Issued:')
        try: issued=datetime.strptime(issued_raw,'%m/%d/%Y').date().isoformat()
        except ValueError: continue

        address=after('Address:')
        if not address:
            continue

        valuation=None
        value_raw=after('Valuation:')
        if value_raw:
            try: valuation=float(value_raw.replace('$','').replace(',','').strip())
            except ValueError: valuation=None

        contractor=after('Contractor:') or None

        project_parts=[]
        for pos,value in enumerate(block):
            if value.lower()=='project description:':
                project_parts=block[pos+1:]
                break
        stop_labels={'TOTAL VALUE:','PERMITS'}
        clean_project=[]
        for value in project_parts:
            if value.upper() in stop_labels:
                break
            clean_project.append(value)
        project=' '.join(clean_project).strip() or None

        units=None
        for pos,value in enumerate(block):
            match=re.search(r'#\s*of\s*Units:\s*(\d+)',value,re.I)
            if match:
                units=int(match.group(1)); break
            if re.search(r'#\s*of\s*Units:\s*$',value,re.I) and pos+1 < len(block):
                next_value=block[pos+1].strip()
                if next_value.isdigit(): units=int(next_value)
                break

        if category=='RESIDENTIAL' and 'new' in subtype_lower:
            permit_type='New Residential'
        elif 'shell' in subtype_lower:
            permit_type='Commercial Shell Building'
        else:
            permit_type='Commercial New'

        out.append(Permit(
            state='ID',jurisdiction=jurisdiction,permit_number=pno,issued_date=issued,
            permit_type=permit_type,address=address,source_name=f'{jurisdiction} permit report',
            source_url=url,project_name=project,building_use=project,units=units,
            valuation=valuation,contractor=contractor,
            raw={'section':f'{category} {subtype}'.strip(),'context':block_text},
        ))
    return out

def parse_generic(text,jurisdiction,url):
    lines=[re.sub(r'\s+',' ',x).strip() for x in text.splitlines() if x.strip()]
    out=[]
    date_re=re.compile(r'\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](20\d\d)\b')
    permit_re=re.compile(r'\b(?:[A-Z]{1,8}-[A-Z]{1,12}-\d{4}-\d{3,6}|[A-Z]{1,8}-\d{4,}[A-Z0-9-]*|(?:BLD|BLDG|BP|RES|COM|SFR|MFR)[- ]?[A-Z0-9-]*\d[A-Z0-9-]*)\b',re.I)
    address_re=re.compile(r'\b\d{1,6}\s+[A-Z0-9].*\b(?:ST|AVE|RD|DR|LN|WAY|CT|BLVD|HWY|PL|PKWY|CIR|TER)\b',re.I)
    signals=('commercial new','residential new','new single','single family dwelling','new commercial','new building','new residential','townhome','town home','duplex','fourplex','multifamily','multi-family','apartment','shell building','shell')
    for idx,line in enumerate(lines):
        if not any(s in line.lower() for s in signals): continue
        nearby=lines[max(0,idx-8):min(len(lines),idx+12)]
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
        project=next((x.split(':',1)[1].strip() for x in nearby if x.lower().startswith('project description:') and ':' in x),line)
        contractor=None
        for x in nearby:
            if x.lower().startswith('contractor:'):
                contractor=x.split(':',1)[1].strip() or None
                break
        out.append(Permit('ID',jurisdiction,pno,issued,line,addr,f'{jurisdiction} permit report',url,project_name=project,valuation=valuation,contractor=contractor,raw={'context':chunk}))
    return out

MeridianCollector=lambda: MeridianDirectCollector()
NampaCollector=lambda: LatestPermitReportCollector('Nampa','https://www.cityofnampa.us/427/Permit-Reports',('08/03/2026','08/10/2026','08/17/2026','08/24/2026','August 2026'))
