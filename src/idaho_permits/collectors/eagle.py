from __future__ import annotations
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import CollectorResult
from .common import get
from ..models import Permit

PORTAL_URL = 'https://eagle_permit.portal.iworq.net/EAGLE/permits/600'


def _clean(value):
    return re.sub(r'\s+', ' ', (value or '').strip())


def _date(value):
    text = _clean(value)
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
    if not m:
        return text
    month, day, year = map(int, m.groups())
    return f'{year:04d}-{month:02d}-{day:02d}'


def _detail_scope(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    text = '\n'.join(_clean(x) for x in soup.stripped_strings if _clean(x))
    labels = (
        'description', 'project description', 'scope of work', 'work description',
        'type of work', 'project name', 'permit description', 'construction type',
    )
    lines = [line for line in text.splitlines() if line]
    hits = []
    for i, line in enumerate(lines):
        low = line.lower().rstrip(':')
        if any(low == label or low.startswith(label + ':') for label in labels):
            if ':' in line and _clean(line.split(':', 1)[1]):
                hits.append(_clean(line.split(':', 1)[1]))
            elif i + 1 < len(lines):
                hits.append(_clean(lines[i + 1]))
    if hits:
        return ' | '.join(dict.fromkeys(hits))[:4000]
    return _clean(' '.join(lines))[:4000]


def permits_from_listing(html: str, base_url: str = PORTAL_URL):
    soup = BeautifulSoup(html, 'html.parser')
    permits = []
    seen = set()
    for row in soup.select('table tr'):
        cells = row.find_all('td')
        if len(cells) < 5:
            continue
        permit_number = _clean(cells[0].get_text(' ', strip=True))
        issued_date = _date(cells[1].get_text(' ', strip=True))
        permit_type = _clean(cells[2].get_text(' ', strip=True))
        address = _clean(cells[3].get_text(' ', strip=True))
        status = _clean(cells[4].get_text(' ', strip=True))
        if not permit_number or permit_number in seen:
            continue
        seen.add(permit_number)
        if not permit_type.lower().startswith('building '):
            continue
        link = cells[0].find('a', href=True) or row.find('a', href=True)
        detail_url = urljoin(base_url, link['href']) if link else base_url
        permits.append({
            'permit_number': permit_number,
            'issued_date': issued_date,
            'permit_type': permit_type,
            'address': address,
            'status': status,
            'detail_url': detail_url,
        })
    return permits


class EaglePermitCollector:
    name = 'Eagle'
    landing_url = PORTAL_URL

    def collect(self):
        listing = get(PORTAL_URL)
        rows = permits_from_listing(listing.text, listing.url)
        permits = []
        detail_failures = 0
        for row in rows:
            scope = ''
            try:
                detail = get(row['detail_url'], referer=listing.url)
                scope = _detail_scope(detail.text)
            except Exception:
                detail_failures += 1
            permits.append(Permit(
                state='ID',
                jurisdiction='Eagle',
                permit_number=row['permit_number'],
                issued_date=row['issued_date'],
                permit_type=row['permit_type'],
                address=row['address'],
                source_name='Eagle iWorQ Permit Portal',
                source_url=row['detail_url'],
                project_name=scope or None,
                building_use=scope or None,
                status=row['status'] or None,
                city='Eagle',
                county='Ada',
                stage='PERMITTED',
                raw={'listing': row, 'detail_scope': scope},
            ))
        note = 'Official City of Eagle iWorQ public permit portal; rolling live building-permit source'
        if detail_failures:
            note += f'; {detail_failures} detail page(s) unavailable, retained fail-closed listing metadata'
        return CollectorResult('Eagle', PORTAL_URL, permits, note)
