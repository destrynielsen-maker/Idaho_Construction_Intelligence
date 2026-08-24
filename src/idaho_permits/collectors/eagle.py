from __future__ import annotations
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import CollectorResult
from .common import get
from ..models import Permit

PORTAL_URL = 'https://portal.iworq.net/EAGLE/permits/600'


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


def _append_record(permits, seen, permit_number, issued_date, permit_type, address, status, detail_url):
    permit_number = _clean(permit_number)
    permit_type = _clean(permit_type)
    if not permit_number or permit_number in seen:
        return
    seen.add(permit_number)
    if not permit_type.lower().startswith('building '):
        return
    permits.append({
        'permit_number': permit_number,
        'issued_date': _date(issued_date),
        'permit_type': permit_type,
        'address': _clean(address),
        'status': _clean(status),
        'detail_url': detail_url,
    })


def permits_from_listing(html: str, base_url: str = PORTAL_URL):
    soup = BeautifulSoup(html, 'html.parser')
    permits = []
    seen = set()

    # Desktop markup when iWorQ renders a conventional table.
    for row in soup.select('table tr'):
        cells = row.find_all('td')
        if len(cells) < 5:
            continue
        link = cells[0].find('a', href=True) or row.find('a', href=True)
        detail_url = urljoin(base_url, link['href']) if link else base_url
        _append_record(
            permits, seen,
            cells[0].get_text(' ', strip=True),
            cells[1].get_text(' ', strip=True),
            cells[2].get_text(' ', strip=True),
            cells[3].get_text(' ', strip=True),
            cells[4].get_text(' ', strip=True),
            detail_url,
        )

    # iWorQ's server response can use responsive/mobile cards instead of a literal
    # table. Parse the labeled card text as a fallback and use the permit-number
    # anchor to recover the stable detail URL.
    links = {}
    for a in soup.find_all('a', href=True):
        label = _clean(a.get_text(' ', strip=True))
        if re.fullmatch(r'\d{4,}', label):
            links.setdefault(label, urljoin(base_url, a['href']))
    text = '\n'.join(_clean(x) for x in soup.stripped_strings if _clean(x))
    card_pattern = re.compile(
        r'Permit\s*#:\s*(\d{4,})\s+'
        r'Date:\s*(\d{1,2}/\d{1,2}/\d{4})\s+'
        r'Permit\s*Type:\s*(.*?)\s+'
        r'Permit\s*Address:\s*(.*?)\s+'
        r'Status:\s*(.*?)\s*'
        r'(?=Inspection Request|Request An Inspection|View\b|Permit\s*#:|Accessibility\b|$)',
        re.IGNORECASE | re.DOTALL,
    )
    for match in card_pattern.finditer(text):
        number, date, permit_type, address, status = match.groups()
        _append_record(
            permits, seen, number, date, permit_type, address, status,
            links.get(number, base_url),
        )
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
