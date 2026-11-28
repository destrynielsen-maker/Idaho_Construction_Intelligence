from __future__ import annotations

from datetime import date, datetime
import re
from io import BytesIO
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

from .base import CollectorResult
from .common import discover_links, get
from .issued_progress import issued_progress
from ..models import Permit


class NampaPermitCollector:
    """Collect the newest published City of Nampa weekly Permit Activity Type report."""

    name = 'Nampa'
    landing_url = 'https://www.cityofnampa.us/427/Permit-Reports'
    freshness_days = 14
    # Public download explicitly linked under the City's Permit Activity Type reports.
    direct_report = ('10/19/2026 – 10/23/2026','https://www.cityofnampa.us/DocumentCenter/View/20941/Weekly-Permit-Activity-Report-10-19-2026---10-23-2026')

    @staticmethod
    def _report_end(label: str):
        dates = re.findall(r'\b\d{1,2}/\d{1,2}/20\d{2}\b', label or '')
        if not dates:
            return None
        try:
            return datetime.strptime(dates[-1], '%m/%d/%Y').date()
        except ValueError:
            return None

    def _weekly_reports(self):
        reports = []
        for label, url in discover_links(self.landing_url):
            end = self._report_end(label)
            if not end or end > date.today() or not _official_weekly_url(url):
                continue
            reports.append((end, label, url))
        reports.sort(key=lambda item: (item[0], item[1], item[2]))
        return reports

    def collect(self):
        from .nampa_css import enabled, collect_css
        if not enabled():
            return self._collect_pdf()
        prior_error = None
        try:
            prior = self._collect_pdf()
            if prior.status == 'ok' or prior.latest_issued_date and (date.today() - date.fromisoformat(prior.latest_issued_date)).days <= 7:
                return prior
        except RuntimeError as exc:
            prior, prior_error = None, exc
        try:
            return collect_css()
        except (RuntimeError, ValueError, OSError):
            if prior is not None:
                prior.note += ' Civic Access fallback did not yield a validated current batch.'
                return prior
            raise RuntimeError('City weekly PDF unavailable; Civic Access fallback did not yield a validated current batch.') from prior_error

    def _collect_pdf(self):
        discovery_error=''
        try:
            reports=self._weekly_reports()
        except requests.RequestException as exc:
            reports=[]
            discovery_error=f'Listing unavailable ({type(exc).__name__}); '
        label,url=self.direct_report
        candidates=[*reversed(reports[-3:]),(self._report_end(label),label,url)]
        tried=set()
        rejected=[]
        for end,label,url in candidates:
            if url in tried:continue
            tried.add(url)
            try:
                response=get(url, referer=self.landing_url)
                if not _official_weekly_url(response.url) or not response.content.startswith(b'%PDF'):
                    raise ValueError('not an official weekly PDF')
                reader=PdfReader(BytesIO(response.content))
                text='\n'.join(page.extract_text() or '' for page in reader.pages)
                if not re.search(r'CITY OF NAMPA,\s*Department of Building Safety',text,re.I) or not re.search(r'Permit Activity Type Report',text,re.I):
                    raise ValueError('unrecognized City permit report')
                period=_published_period(text)
                dates=_contained_dates(text)
                if not period or period[1]!=end or not dates or not all(period[0]<=d<=end for d in dates):
                    raise ValueError('report period or labeled issue dates not verified')
                try:
                    layout='\n'.join(page.extract_text(extraction_mode='layout') or '' for page in reader.pages)
                except Exception:
                    layout=''  # Dates remain usable; do not borrow names from flattened PDF text.
                permits=parse_nampa(text,self.name,url,layout=layout,period=period)
            except (requests.RequestException,ValueError,OSError) as exc:
                rejected.append(f'{label}: {type(exc).__name__}')
                continue
            newest=max(dates)
            age=(date.today()-newest).days
            state='stale' if age>self.freshness_days else 'degraded' if discovery_error or rejected else 'ok'
            report_mode='City-linked direct fallback' if not reports or not any(x[2]==url for x in reports) else 'City listing'
            note=(f'{discovery_error}{report_mode}: {label}; {len(permits)} new-construction records parsed; '
                  f'last labeled issue date {newest.isoformat()} ({age} days old).')
            if rejected:note+=' Unavailable/newer assets: '+', '.join(rejected)+'.'
            if state=='stale':note+=f' WARNING: latest verified issue date is older than {self.freshness_days} days.'
            return CollectorResult(self.name, url, permits, note, status=state,
                latest_issued_date=newest.isoformat(), report_period_end=end.isoformat(),
                progress=[issued_progress(permit) for permit in permits], progress_complete=True,
                progress_source_name='Nampa weekly permit activity report (issued new construction)')
        raise RuntimeError(f'{discovery_error}No validated City weekly PDF; {", ".join(rejected) or "no linked report"}')


def _official_weekly_url(url):
    target=urlparse(url)
    return (target.scheme=='https' and target.netloc=='www.cityofnampa.us'
            and '/documentcenter/view/' in target.path.lower()
            and 'permit-activity-report-' in target.path.lower())


def _published_period(text):
    found=re.search(r'^\s*(\d{1,2}/\d{1,2}/20\d{2})\s+to\s+(\d{1,2}/\d{1,2}/20\d{2})\s*$',text,re.I|re.M)
    if not found:return None
    try:return tuple(datetime.strptime(x,'%m/%d/%Y').date() for x in found.groups())
    except ValueError:return None


def _contained_dates(text):
    dates=[]
    for line in text.splitlines():
        token,_=_issue_and_project(line.strip())
        if token:
            try:dates.append(datetime.strptime(token,'%m/%d/%Y').date())
            except ValueError:continue
    return dates


def _organizations_from_layout(layout):
    # The report prints separate Contact Type / Name / Associated Company columns.
    # Layout extraction preserves that distinction; flattened extraction does not.
    matches={}
    permit=''
    for line in layout.splitlines():
        match=re.match(r'^\s*Permit Number:\s*([A-Z0-9-]+)\s+Situs:',line,re.I)
        if match:
            permit=match.group(1).upper()
            continue
        if not permit:continue
        columns=re.split(r'\s{5,}',line.strip())
        if len(columns)!=3:continue
        role,person,company=columns
        if not re.search(r'\bRegistered Building(?: Contractor)?$',role,re.I):continue
        company=re.sub(r'\s+',' ',company.strip())
        if not company or company.casefold()==person.casefold() and not re.search(r'\b(llc|inc|corp|company|construction|homes|builders)\b',company,re.I):
            continue
        matches.setdefault(permit,set()).add(company)
    # Multiple registered contractors remain ambiguous; never pick one on list order.
    return {p:next(iter(values)) for p,values in matches.items() if len(values)==1}


def _new_construction_signal(project_type: str, structure_use: str, project_name: str, scope: str) -> bool:
    text = ' '.join(x for x in (project_type, structure_use, project_name, scope) if x)
    low = re.sub(r'\s+', ' ', text).strip().lower()

    explicit = (
        r'\bnew\s+construction\b',
        r'\bnew\s+sfd\b',
        r'\bnew\s+single[- ]family\b',
        r'\bnew\s+residential\b',
        r'\bnew\s+multifamily\b',
        r'\bnew\s+multi-family\b',
        r'\bnew\s+apartment\b',
        r'\bnew\s+(?:sf\s+)?town(?:home|house)\b',
        r'\bnew\s+duplex\b',
        r'\bnew\s+triplex\b',
        r'\bnew\s+fourplex\b',
        r'\bnew\s+complete\s+building\b',
        r'\bnew\s+shell\b',
        r'\bshell building\s+(?:to be\s+)?construct(?:ed|ion)\b',
        r'\bground[- ]up\b',
        r'\bconstruct(?:ion)?\b.{0,80}\bnew\b.{0,80}\b(?:building|dwelling|home|residence|warehouse|facility)\b',
    )
    if not any(re.search(pattern, low, re.I) for pattern in explicit):
        return False

    # Explicit ground-up/new-construction language wins. Otherwise suppress common Nampa
    # non-new scopes that may still contain words such as "new" for finishes or equipment.
    if re.search(r'\bnew\s+construction\b|\bnew\s+sfd\b|\bground[- ]up\b', low, re.I):
        return True
    noise = (
        'addition', 'remodel', 'tenant improvement', 'occupancy only', 're-roof', 'reroof',
        'repair', 'replacement', 'patio cover', 'carport', 'sign', 'interior partition',
    )
    return not any(term in low for term in noise)


def _issue_and_project(value: str):
    patterns = (
        r'Issue Date:\s*(\d{1,2}/\d{1,2}/20\d{2})\s*Project Name:\s*(.*)$',
        r'^(\d{1,2}/\d{1,2}/20\d{2})\s*Issue Date:\s*Project Name:\s*(.*)$',
    )
    for pattern in patterns:
        match = re.search(pattern, value, re.I)
        if match:
            return match.group(1), match.group(2).strip()
    return '', ''


def _unit_value(value: str):
    if value.lower().startswith('unit:'):
        return value.split(':', 1)[1].strip()
    match = re.match(r'^([\d.]+)\s*Unit:\s*$', value, re.I)
    return match.group(1) if match else ''


def parse_nampa(text: str, jurisdiction: str, url: str, *, layout='', period=None) -> list[Permit]:
    """Parse Nampa's pypdf token stream by permit block.

    Nampa's PDFs invert several rendered label/value pairs in extraction (for example
    ``09/04/2026Issue Date:`` and ``1.00Unit:``), so the parser accepts both the rendered and
    extracted orders while anchoring every record on its own ``Permit Number`` line.
    """
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip()]
    out = []
    organizations=_organizations_from_layout(layout)
    project_type = ''
    structure_use = ''
    permit_line = re.compile(r'^Permit Number:\s*([A-Z0-9-]+)\s+Situs:\s*(.+)$', re.I)

    for i, line in enumerate(lines):
        if line.lower().startswith('project type:'):
            project_type = line.split(':', 1)[1].strip()
            continue
        if line.lower().startswith('structure use:'):
            structure_use = line.split(':', 1)[1].strip()
            continue

        match = permit_line.match(line)
        if not match:
            continue

        number = match.group(1).strip()
        address = match.group(2).strip()
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if permit_line.match(lines[j]) or lines[j].lower().startswith('project type:') or lines[j].lower().startswith('structure use:'):
                end = j
                break
        block = lines[i:end]

        issued = ''
        project_name_parts = []
        scope_parts = []
        valuation = None
        units = None
        contractor = None

        for value in block[1:5]:
            money = re.search(r'\$\s*([\d,]+(?:\.\d+)?)', value)
            if money:
                try:
                    valuation = float(money.group(1).replace(',', ''))
                except ValueError:
                    pass
                break

        for pos, value in enumerate(block):
            issue_raw, project_start = _issue_and_project(value)
            if issue_raw:
                try:
                    issued = datetime.strptime(issue_raw, '%m/%d/%Y').date().isoformat()
                except ValueError:
                    issued = ''
                if project_start:
                    project_name_parts.append(project_start)
                nxt = pos + 1
                while nxt < len(block):
                    candidate = block[nxt]
                    if _unit_value(candidate) or candidate.lower() == 'unit:' or candidate.lower().startswith('scope of work:'):
                        break
                    project_name_parts.append(candidate)
                    nxt += 1

            unit_text = _unit_value(value)
            if unit_text:
                try:
                    units = int(float(unit_text))
                except ValueError:
                    units = None

            if value.lower().startswith('scope of work:'):
                scope_parts.append(value.split(':', 1)[1].strip())
                nxt = pos + 1
                while nxt < len(block):
                    candidate = block[nxt]
                    if re.search(r'(Applicant|Owner\s*\d*|Tenant|Foreman|Designer|Registered Building Contractor|Permit\(s\)|Project Type Valuation|Tax Account:)', candidate, re.I):
                        break
                    if re.match(r'^\d{1,2}/\d{1,2}/20\d{2}\s+Page\s+\d+', candidate, re.I):
                        nxt += 1
                        continue
                    if re.match(r'^\d{1,2}/\d{1,2}/20\d{2}\s+to\s+\d{1,2}/\d{1,2}/20\d{2}$', candidate, re.I):
                        nxt += 1
                        continue
                    scope_parts.append(candidate)
                    nxt += 1

        project_name = ' '.join(project_name_parts).strip() or None
        scope = ' '.join(scope_parts).strip()
        if not issued or not _new_construction_signal(project_type, structure_use, project_name or '', scope):
            continue
        issued_value=date.fromisoformat(issued)
        if issued_value>date.today() or period and not period[0]<=issued_value<=period[1]:
            continue
        contractor=organizations.get(number.upper())

        combined = ' '.join(x for x in (structure_use, project_name or '', scope) if x)
        if re.search(r'\b(?:duplex|triplex|fourplex|multifamily|multi-family|apartment|townhome|townhouse)\b', combined, re.I):
            permit_type = 'New Multifamily'
        elif project_type.lower() == 'commercial':
            permit_type = 'Commercial New Construction'
        else:
            permit_type = 'New Residential'

        out.append(Permit(
            state='ID',
            jurisdiction=jurisdiction,
            permit_number=number,
            issued_date=issued,
            permit_type=permit_type,
            address=address,
            source_name=f'{jurisdiction} weekly permit activity report',
            source_url=url,
            project_name=project_name,
            building_use=scope or structure_use or None,
            units=units,
            valuation=valuation,
            contractor=contractor,
            raw={
                'project_type': project_type,
                'structure_use': structure_use,
                'scope': scope,
                'contractor_role': 'Registered Building Contractor / Associated Company' if contractor else None,
            },
        ))

    return out
