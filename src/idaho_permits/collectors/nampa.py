from __future__ import annotations

from datetime import date, datetime
import re

from .base import CollectorResult
from .common import discover_links, get, pdf_text
from ..models import Permit


class NampaPermitCollector:
    """Collect the newest published City of Nampa weekly Permit Activity Type report."""

    name = 'Nampa'
    landing_url = 'https://www.cityofnampa.us/427/Permit-Reports'
    freshness_days = 14

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
            if not end:
                continue
            if '/DocumentCenter/View/' not in url and '.pdf' not in url.lower():
                continue
            reports.append((end, label, url))
        reports.sort(key=lambda item: (item[0], item[1], item[2]))
        return reports

    def collect(self):
        reports = self._weekly_reports()
        if not reports:
            return CollectorResult(
                self.name,
                self.landing_url,
                [],
                'No published weekly Permit Activity Type report links were discoverable; source remains visible for manual prospecting',
            )

        end, label, url = reports[-1]
        response = get(url, referer=self.landing_url)
        ctype = response.headers.get('content-type', '').lower()
        if 'pdf' not in ctype and not response.content.startswith(b'%PDF'):
            return CollectorResult(
                self.name,
                url,
                [],
                f'Newest published weekly report was not a PDF ({label}); source remains visible for manual prospecting',
            )

        permits = parse_nampa(pdf_text(response.content), self.name, url)
        age = (date.today() - end).days
        note = f'Latest discovered report: {label}; {len(permits)} new-construction records parsed; report ended {age} days ago'
        if age > self.freshness_days:
            note += f' WARNING: newest published Nampa weekly report is older than {self.freshness_days} days'
        return CollectorResult(self.name, url, permits, note)


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


def parse_nampa(text: str, jurisdiction: str, url: str) -> list[Permit]:
    """Parse Nampa's pypdf token stream by permit block.

    Nampa's PDFs invert several rendered label/value pairs in extraction (for example
    ``09/04/2026Issue Date:`` and ``1.00Unit:``), so the parser accepts both the rendered and
    extracted orders while anchoring every record on its own ``Permit Number`` line.
    """
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip()]
    out = []
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

            if 'registered building contractor' in value.lower() and not contractor:
                before = re.split(r'Registered Building Contractor', value, maxsplit=1, flags=re.I)[0]
                before = re.sub(r'(Applicant|Owner\s*\d*|Tenant|Foreman|Designer)[, ]*$', '', before, flags=re.I).strip(' ,-')
                contractor = before or None

        project_name = ' '.join(project_name_parts).strip() or None
        scope = ' '.join(scope_parts).strip()
        if not issued or not _new_construction_signal(project_type, structure_use, project_name or '', scope):
            continue

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
                'context': ' | '.join(block),
            },
        ))

    return out
