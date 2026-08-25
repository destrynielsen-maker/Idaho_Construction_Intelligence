from __future__ import annotations
from datetime import date
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .common import get, pdf_text

REPORTS_URL = 'https://www.cityofcaldwell.org/Departments/Community-Development/Building-Safety-Division/Building-Bulletins-Reports'

MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
}


def _clean(value):
    return ' '.join((value or '').split())


def report_links_from_page(html: str, base_url: str = REPORTS_URL):
    soup = BeautifulSoup(html, 'html.parser')
    reports = []
    for a in soup.find_all('a', href=True):
        label = _clean(a.get_text(' ', strip=True))
        m = re.search(
            r'\b(' + '|'.join(MONTHS) + r')\s+(20\d{2})\b',
            label.lower(),
        )
        if not m:
            continue
        month = MONTHS[m.group(1)]
        year = int(m.group(2))
        href = urljoin(base_url, a['href'])
        hay = (label + ' ' + href).lower()
        if '.pdf' not in hay and 'download' not in hay and '/files/' not in hay:
            continue
        reports.append({
            'label': label,
            'year': year,
            'month': month,
            'report_date': date(year, month, 1).isoformat(),
            'url': href,
        })
    unique = {}
    for row in reports:
        unique[(row['year'], row['month'])] = row
    return sorted(unique.values(), key=lambda x: (x['year'], x['month']))


class CaldwellReportDiscoveryCollector:
    name = 'Caldwell'
    landing_url = REPORTS_URL

    def collect(self):
        page = get(REPORTS_URL, timeout=60)
        reports = report_links_from_page(page.text, page.url)
        if not reports:
            raise RuntimeError('No official Caldwell monthly building report links discovered')
        latest = reports[-1]
        response = get(latest['url'], timeout=90, referer=page.url)
        content_type = (response.headers.get('content-type') or '').lower()
        if not response.content.startswith(b'%PDF') and 'pdf' not in content_type:
            raise RuntimeError(
                f"Latest Caldwell report is not a PDF: label={latest['label']!r} url={latest['url']} content_type={content_type!r}"
            )
        text = pdf_text(response.content)
        excerpt = _clean(text)[:7000]
        if not excerpt:
            raise RuntimeError(f"Latest Caldwell PDF has no extractable text: {latest['url']}")
        raise RuntimeError(
            f"Official Caldwell report discovery only; reports={reports[-6:]}; latest={latest}; text_excerpt={excerpt}"
        )
