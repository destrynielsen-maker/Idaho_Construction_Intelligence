from __future__ import annotations
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from .base import CollectorResult
from .common import get
from ..models import Permit

PORTAL_URL = 'https://portal.iworq.net/EAGLE/permits/600'
DETAIL_PATH_RE = re.compile(r'/EAGLE/permit/600/\d+$', re.IGNORECASE)


def _clean(value):
    return re.sub(r'\s+', ' ', (value or '').strip())


def _date(value):
    text = _clean(value)
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
    if not m:
        return text
    month, day, year = map(int, m.groups())
    return f'{year:04d}-{month:02d}-{day:02d}'


def _lines(html: str):
    soup = BeautifulSoup(html, 'html.parser')
    return [_clean(x) for x in soup.stripped_strings if _clean(x)]


def _label_value(lines, aliases):
    aliases = tuple(a.lower().rstrip(':') for a in aliases)
    for i, line in enumerate(lines):
        low = line.lower().strip()
        base = low.rstrip(':')
        for alias in aliases:
            if base == alias:
                if i + 1 < len(lines):
                    return _clean(lines[i + 1])
            if low.startswith(alias + ':'):
                value = _clean(line.split(':', 1)[1])
                if value:
                    return value
    return ''


def _detail_scope(html: str) -> str:
    lines = _lines(html)
    labels = (
        'description', 'project description', 'scope of work', 'work description',
        'type of work', 'project name', 'permit description', 'construction type',
    )
    hits = []
    for label in labels:
        value = _label_value(lines, (label,))
        if value and value not in hits:
            hits.append(value)
    if hits:
        return ' | '.join(hits)[:4000]
    return ''


def _append_record(permits, seen, permit_number, issued_date, permit_type, address, status, detail_url, scope=''):
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
        'scope': _clean(scope),
    })


def detail_links_from_shell(html: str, base_url: str = PORTAL_URL):
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    seen = set()
    for a in soup.find_all('a', href=True):
        url = urljoin(base_url, a['href'])
        if not DETAIL_PATH_RE.fullmatch(urlparse(url).path):
            continue
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def record_from_detail(html: str, detail_url: str):
    lines = _lines(html)
    permit_number = _label_value(lines, ('permit #', 'permit number', 'permit no'))
    issued_date = _label_value(lines, ('date', 'permit date', 'issued date', 'issue date'))
    permit_type = _label_value(lines, ('permit type', 'type'))
    address = _label_value(lines, ('permit address', 'project address', 'site address', 'address'))
    status = _label_value(lines, ('status', 'permit status'))
    scope = _detail_scope(html)
    if not permit_number:
        return None
    return {
        'permit_number': permit_number,
        'issued_date': _date(issued_date),
        'permit_type': permit_type,
        'address': address,
        'status': status,
        'detail_url': detail_url,
        'scope': scope,
    }


def permits_from_listing(html: str, base_url: str = PORTAL_URL):
    soup = BeautifulSoup(html, 'html.parser')
    permits = []
    seen = set()
    for row in soup.select('table tr'):
        cells = row.find_all('td')
        if len(cells) < 5:
            continue
        link = cells[0].find('a', href=True) or row.find('a', href=True)
        detail_url = urljoin(base_url, link['href']) if link else base_url
        _append_record(permits, seen, cells[0].get_text(' ', strip=True), cells[1].get_text(' ', strip=True), cells[2].get_text(' ', strip=True), cells[3].get_text(' ', strip=True), cells[4].get_text(' ', strip=True), detail_url)
    links = {}
    for a in soup.find_all('a', href=True):
        label = _clean(a.get_text(' ', strip=True))
        if re.fullmatch(r'\d{4,}', label):
            links.setdefault(label, urljoin(base_url, a['href']))
    text = '\n'.join(_clean(x) for x in soup.stripped_strings if _clean(x))
    card_pattern = re.compile(r'Permit\s*#:\s*(\d{4,})\s+Date:\s*(\d{1,2}/\d{1,2}/\d{4})\s+Permit\s*Type:\s*(.*?)\s+Permit\s*Address:\s*(.*?)\s+Status:\s*(.*?)\s*(?=Inspection Request|Request An Inspection|View\b|Permit\s*#:|Accessibility\b|$)', re.IGNORECASE | re.DOTALL)
    for match in card_pattern.finditer(text):
        number, date, permit_type, address, status = match.groups()
        _append_record(permits, seen, number, date, permit_type, address, status, links.get(number, base_url))
    return permits


def _zero_payload_diagnostic(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    title = _clean(soup.title.get_text(' ', strip=True) if soup.title else '')[:80] or 'none'
    return f'zero parsed; html_bytes={len(html.encode("utf-8"))}; title={title}; detail_links={len(detail_links_from_shell(html))}'


class EaglePermitCollector:
    name = 'Eagle'
    landing_url = PORTAL_URL

    def collect(self):
        listing = get(PORTAL_URL)
        rows = permits_from_listing(listing.text, listing.url)
        detail_failures = 0
        detail_unparsed = 0
        detail_samples = []
        if not rows:
            seen = set()
            for detail_url in detail_links_from_shell(listing.text, listing.url):
                try:
                    detail = get(detail_url, referer=listing.url)
                    row = record_from_detail(detail.text, detail.url)
                except Exception:
                    detail_failures += 1
                    continue
                if not row:
                    detail_unparsed += 1
                    continue
                if len(detail_samples) < 8:
                    detail_samples.append(f"{row['permit_number']}|{row['permit_type'][:80]}|{row['scope'][:100]}")
                _append_record(rows, seen, row['permit_number'], row['issued_date'], row['permit_type'], row['address'], row['status'], row['detail_url'], row['scope'])
        if not rows:
            diag = _zero_payload_diagnostic(listing.text)
            raise RuntimeError(f'{diag}; detail_failures={detail_failures}; detail_unparsed={detail_unparsed}; detail_samples={detail_samples}')
        permits = []
        for row in rows:
            scope = row.get('scope') or ''
            if not scope:
                try:
                    detail = get(row['detail_url'], referer=listing.url)
                    scope = _detail_scope(detail.text)
                except Exception:
                    detail_failures += 1
            permits.append(Permit(state='ID', jurisdiction='Eagle', permit_number=row['permit_number'], issued_date=row['issued_date'], permit_type=row['permit_type'], address=row['address'], source_name='Eagle iWorQ Permit Portal', source_url=row['detail_url'], project_name=scope or None, building_use=scope or None, status=row['status'] or None, city='Eagle', county='Ada', stage='PERMITTED', raw={'listing': row, 'detail_scope': scope}))
        note = 'Official City of Eagle iWorQ public permit portal; crawls public current permit detail links when rows are client-rendered'
        if detail_failures:
            note += f'; {detail_failures} detail request(s) unavailable'
        if detail_unparsed:
            note += f'; {detail_unparsed} detail page(s) lacked a displayed permit number'
        return CollectorResult('Eagle', PORTAL_URL, permits, note)
