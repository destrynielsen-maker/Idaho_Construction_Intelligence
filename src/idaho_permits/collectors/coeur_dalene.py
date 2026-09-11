from __future__ import annotations

from datetime import date, datetime, timedelta
import re

import requests

from .base import CollectorResult
from .common import BROWSER_HEADERS, pdf_text
from ..models import Permit


REPORT_URL = 'https://building.cdaid.org/Reports/IssuedPermits'


class CoeurDAleneCollector:
    name = "Coeur d'Alene"
    landing_url = REPORT_URL
    window_days = 45

    def collect(self):
        end = date.today()
        start = end - timedelta(days=self.window_days - 1)
        response = requests.post(
            REPORT_URL,
            data={
                'StartDate': start.strftime('%m/%d/%Y'),
                'EndDate': end.strftime('%m/%d/%Y'),
            },
            timeout=60,
            headers=BROWSER_HEADERS,
            allow_redirects=True,
        )
        response.raise_for_status()
        ctype = response.headers.get('content-type', '').lower()
        if 'pdf' not in ctype and not response.content.startswith(b'%PDF'):
            return CollectorResult(
                self.name,
                REPORT_URL,
                [],
                f'Official date-range issued-permit report did not return a PDF for {start.isoformat()} through {end.isoformat()}',
            )

        permits = parse(pdf_text(response.content), REPORT_URL)
        newest = max((p.issued_date for p in permits if p.issued_date), default=None)
        note = (
            f'Official City of Coeur d\'Alene issued building permits; rolling {self.window_days}-day report '
            f'{start.isoformat()} through {end.isoformat()}; {len(permits)} primary building permits parsed'
        )
        if newest:
            note += f'; newest primary building permit issued {newest}'
        return CollectorResult(self.name, REPORT_URL, permits, note)


def money(value: str | None):
    if not value:
        return None
    try:
        return float(value.replace('$', '').replace(',', ''))
    except ValueError:
        return None


def _accessory_only(project: str) -> bool:
    proj = re.sub(r'\s+', ' ', project or '').strip().lower()
    if not re.search(r'\b(?:deck|patio cover|carport|detached garage|shed|accessory structure)\b', proj):
        return False
    # Do not suppress an actual dwelling merely because its description also mentions a garage/deck.
    return not re.search(
        r'\b(?:sfr|single[- ]family|dwelling|home|residence|duplex|triplex|fourplex|town\s*house|townhouse|apartment|multifamily|multi-family)\b',
        proj,
    )


def _project_permit_type(city_type: str, project: str) -> str:
    """Map strong Coeur d'Alene ground-up signals into the shared classifier vocabulary."""
    typ = re.sub(r'\s+', ' ', city_type or '').strip().lower()
    proj = re.sub(r'\s+', ' ', project or '').strip().lower()

    if _accessory_only(project):
        return 'Accessory Structure'
    if typ == 'duplex' and ('duplex' in proj or not proj):
        return 'New Multifamily Duplex'
    if typ in {'town house', 'townhouse'} and re.search(r'\btown\s*house\b|\btownhouse\b', proj):
        return 'New Multifamily Townhouse'
    if typ in {'multi-family', 'multifamily', 'apartment'} and re.search(
        r'\bnew\b|\bbuilding\b|\bapartments?\b|\bmultifamily\b|\bmulti-family\b', proj
    ) and not re.search(r'\b(?:remodel|alteration|repair|conversion|reroof|re-roof)\b', proj):
        return 'New Multifamily'
    if typ in {'single-family', 'single family'} and re.search(
        r'\bnew\s+(?:sfr|single[- ]family|residence|home|dwelling)\b|^sfr\b|\bsingle[- ]family\s+(?:residence|home|dwelling)\b',
        proj,
    ) and not re.search(r'\b(?:adu|addition|remodel|alteration|repair|deck|garage|carport|reroof|re-roof)\b', proj):
        return 'New Single Family'
    if typ == 'commercial' and re.search(
        r'\bnew\s+(?:commercial|building|shell|warehouse|office|retail|hotel|industrial)\b|\bground[- ]up\b|\bshell building\b',
        proj,
    ) and not re.search(r'\b(?:addition|remodel|alteration|repair|tenant improvement|demo|demolition)\b', proj):
        return 'New Commercial Construction'
    return city_type


def parse(text: str, source_url: str) -> list[Permit]:
    lines = [re.sub(r'\s+', ' ', x).strip() for x in text.splitlines() if x.strip()]
    out = []
    i = 0
    permit_number_re = re.compile(r'^\d{5,6}-[A-Z0-9]+$', re.I)
    row_re = re.compile(
        r'^(?P<city_type>.*?)'
        r'(?P<issued>\d{2}/\d{2}/\d{4})'
        r'(?P<owner>.*?)\s*'
        r'(?P<valuation>\$[\d,]+(?:\.\d+)?)\s*$',
        re.I,
    )

    while i < len(lines):
        if not (lines[i].startswith('Address:') and ' Project:' in lines[i]):
            i += 1
            continue

        match = re.match(r'Address:\s*(.*?)\s+Project:\s*(.*)', lines[i])
        if not match:
            i += 1
            continue
        address, project = match.groups()

        permit_no = ''
        owner = ''
        issued = ''
        valuation = None
        city_type = ''
        contractor = None
        architect = None

        for j in range(i + 1, min(i + 10, len(lines))):
            if not permit_number_re.match(lines[j]):
                continue
            permit_no = lines[j].upper()
            # Coeur d'Alene publishes engineering/mechanical/plumbing child permits for the same
            # project. Keep only the primary building record so one project is one sales lead.
            if not permit_no.endswith('-B'):
                break

            if j + 1 < len(lines):
                row = lines[j + 1]
                row_match = row_re.match(row)
                if row_match:
                    city_type = row_match.group('city_type').strip()
                    try:
                        issued = datetime.strptime(row_match.group('issued'), '%m/%d/%Y').date().isoformat()
                    except ValueError:
                        issued = ''
                    owner = row_match.group('owner').strip()
                    valuation = money(row_match.group('valuation'))

            for k in range(j + 2, min(j + 9, len(lines))):
                if lines[k].startswith(('Permit Num:', 'Address:')):
                    break
                if lines[k].startswith('Contractor:'):
                    contractor = lines[k].split(':', 1)[1].strip() or None
                if lines[k].startswith(('Architect:', 'Draftsman:', 'Draftsmen:')) and not architect:
                    architect = lines[k].split(':', 1)[1].strip() or None
            break

        if permit_no.endswith('-B') and issued:
            permit_type = _project_permit_type(city_type, project)
            building_use = None if permit_type == 'Accessory Structure' else (city_type or None)
            out.append(Permit(
                state='ID',
                jurisdiction="Coeur d'Alene",
                permit_number=permit_no,
                issued_date=issued,
                permit_type=permit_type,
                address=address,
                source_name="Coeur d'Alene Issued Permits",
                source_url=source_url,
                project_name=project,
                building_use=building_use,
                valuation=valuation,
                contractor=contractor,
                owner=owner or None,
                architect=architect,
                raw={
                    'project': project,
                    'city_type': city_type,
                },
            ))
        i += 1

    unique = {permit.permit_number: permit for permit in out}
    return list(unique.values())
