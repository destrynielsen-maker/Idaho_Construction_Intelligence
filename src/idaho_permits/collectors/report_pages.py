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

        # Keep only unique URLs, preferring newly discovered links while retaining direct
        # City-hosted assets as a fail-open path for the public reports themselves.
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

        # Deduplicate because a report may be both discovered and seeded.
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
    """Parse Meridian PDF rows as discrete permit blocks.

    The PDFs place records directly next to each other. Using a broad nearby-text window can
    accidentally pair a new project's description with the previous permit number. This parser
    anchors every record on its own `Permit #` header and carries the active report section
    (for example COMMERCIAL New) into classification fields.
    """
    lines=[re.sub(r'\s+',' ',x).strip() for x in text.splitlines() if x.strip()]
    out=[]; section=''
    permit_header=re.compile(r'\bPermit\s*#\s*([A-Z0-9-]+).*?Issued:\s*(\d{1,2}/\d{1,2}/20\d{2})',re.I)
    section_re=re.compile(r'^(COMMERCIAL|RESIDENTIAL)\s+(.+)$',re.I)

    for idx,line in enumerate(lines):
        sm=section_re.match(line)
        if sm and 'TOTAL VALUE' not in line.upper():
            section=line
        hm=permit_header.search(line)
        if not hm: continue

        end=idx+1
        while end < len(lines):
            if permit_header.search(lines[end]): break
            next_section=section_re.match(lines[end])
            if next_section and 'TOTAL VALUE' not in lines[end].upper(): break
            end += 1
        block=lines[idx:end]
        block_text=' | '.join(block)
        section_lower=section.lower()
        if ' new' not in section_lower and 'shell' not in section_lower:
            continue

        pno=hm.group(1).strip()
        try: issued=datetime.strptime(hm.group(2),'%m/%d/%Y').date().isoformat()
        except ValueError: continue

        address=''
        for value in block:
            if value.lower().startswith('address:'):
                address=value.split(':',1)[1].split('Res.SQF:',1)[0].strip()
                break
        if not address: continue

        valuation=None
        vm=re.search(r'Valuation:\s*\$?([\d,]+(?:\.\d{2})?)',block_text,re.I)
        if vm:
            try: valuation=float(vm.group(1).replace(',',''))
            except ValueError: valuation=None

        project_parts=[]; collecting=False
        for value in block:
            if value.lower().startswith('project description:'):
                collecting=True
                project_parts.append(value.split(':',1)[1].strip())
                continue
            if collecting:
                if re.search(r'\bTOTAL VALUE:',value,re.I): break
                project_parts.append(value)
        project=' '.join(x for x in project_parts if x).strip() or None

        contractor=None
        for pos,value in enumerate(block):
            if value.lower().startswith('contractor:'):
                contractor=value.split(':',1)[1].strip() or None
                if not contractor and pos+1 < len(block): contractor=block[pos+1].strip() or None
                break

        units=None
        um=re.search(r'#\s*of\s*Units:\s*(\d+)',block_text,re.I)
        if um:
            try: units=int(um.group(1))
            except ValueError: units=None

        if section_lower.startswith('residential') and 'new' in section_lower:
            permit_type='New Residential'
        elif 'shell' in section_lower:
            permit_type='Commercial Shell Building'
        else:
            permit_type='Commercial New'

        out.append(Permit(
            state='ID',jurisdiction=jurisdiction,permit_number=pno,issued_date=issued,
            permit_type=permit_type,address=address,source_name=f'{jurisdiction} permit report',
            source_url=url,project_name=project,building_use=project,units=units,
            valuation=valuation,contractor=contractor,raw={'section':section,'context':block_text},
        ))
    return out

def parse_generic(text,jurisdiction,url):
    lines=[re.sub(r'\s+',' ',x).strip() for x in text.splitlines() if x.strip()]
    out=[]
    date_re=re.compile(r'\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](20\d\d)\b')
    # Covers Meridian C-NEW-2026-0023 / C-SHELL-2026-0019 as well as simpler local formats.
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
