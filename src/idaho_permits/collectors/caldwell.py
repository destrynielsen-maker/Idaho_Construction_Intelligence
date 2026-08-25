from __future__ import annotations
from datetime import date
import hashlib
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import CollectorResult
from .common import get
from ..models import Permit

PAGE_TEMPLATE = 'https://compassidaho.org/development-review-checklists-{year}/'
MONTHS = {
    'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
    'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,
}


def _clean(value):
    return ' '.join((value or '').split())


def _stable_number(year: int, month: int, project: str):
    digest = hashlib.sha1(project.lower().encode('utf-8')).hexdigest()[:8].upper()
    return f'COMPASS-{year}{month:02d}-{digest}'


def _building_use(project: str):
    low = project.lower()
    if any(x in low for x in ('townhome','townhomes','apartment','apartments','multifamily','multi-family','condo','condominium')):
        return f'New multifamily development: {project}'
    if any(x in low for x in ('commercial','industrial','retail','hotel','office','business park','shopping')):
        return f'New commercial development: {project}'
    return project


def records_from_page(html: str, base_url: str, default_year: int):
    soup = BeautifulSoup(html, 'html.parser')
    records = []
    current_month = None
    current_year = default_year
    for node in soup.find_all(['h2','h3','h4','h5','table']):
        if node.name != 'table':
            text = _clean(node.get_text(' ', strip=True)).lower()
            m = re.search(r'\b(' + '|'.join(MONTHS) + r')\s+(20\d{2})\b', text)
            if m:
                current_month = MONTHS[m.group(1)]
                current_year = int(m.group(2))
            continue
        if current_month is None:
            continue
        for tr in node.find_all('tr'):
            cells = tr.find_all(['td','th'])
            if len(cells) < 2 or all(c.name == 'th' for c in cells):
                continue
            project = _clean(cells[0].get_text(' ', strip=True))
            agency = _clean(cells[1].get_text(' ', strip=True))
            if not project or 'city of caldwell' not in agency.lower():
                continue
            checklist = None
            application = None
            if len(cells) >= 3:
                a = cells[2].find('a', href=True)
                if a: checklist = urljoin(base_url, a['href'])
            if len(cells) >= 4:
                a = cells[3].find('a', href=True)
                if a: application = urljoin(base_url, a['href'])
            source_url = application or checklist or base_url
            permit_type = 'New development review'
            records.append(Permit(
                state='ID',
                jurisdiction='Caldwell',
                permit_number=_stable_number(current_year,current_month,project),
                issued_date=date(current_year,current_month,1).isoformat(),
                permit_type=permit_type,
                address='Caldwell, ID',
                source_name='COMPASS Development Review',
                source_url=source_url,
                project_name=project,
                building_use=_building_use(project),
                status='Regional development review',
                county='Canyon',
                city='Caldwell',
                stage='PLANNING',
                raw={
                    'agency': agency,
                    'review_month': f'{current_year}-{current_month:02d}',
                    'checklist_url': checklist,
                    'application_url': application,
                },
            ))
    unique = {}
    for permit in records:
        unique[permit.key] = permit
    return list(unique.values())


class CaldwellCompassCollector:
    name = 'Caldwell'

    def __init__(self, year: int | None = None):
        self.year = year or date.today().year
        self.landing_url = PAGE_TEMPLATE.format(year=self.year)

    def collect(self):
        response = get(self.landing_url, timeout=60)
        permits = records_from_page(response.text, response.url, self.year)
        if not permits:
            raise RuntimeError('COMPASS page returned no City of Caldwell development-review records')
        return CollectorResult(
            'Caldwell',
            self.landing_url,
            permits,
            f'Official COMPASS development-review checklist feed; City of Caldwell early-stage projects for {self.year}',
        )
