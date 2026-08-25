from __future__ import annotations
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from .base import CollectorResult
from .common import BROWSER_HEADERS

HOME_URL = 'https://www2.citizenserve.com/Portal/PortalController?Action=showHomePage&ctzPagePrefix=Portal_&installationID=263'
SEARCH_URL = 'https://www2.citizenserve.com/Portal/PortalController?Action=showSearchPage&ctzPagePrefix=Portal_&type=Permit&installationID=263'


def _clean(value):
    return ' '.join((value or '').split())


def summarize_search_page(html: str, base_url: str = SEARCH_URL) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    forms = []
    for form in soup.find_all('form')[:6]:
        controls = []
        for node in form.find_all(['input', 'select', 'textarea', 'button']):
            name = node.get('name') or node.get('id') or ''
            if not name:
                continue
            item = {
                'tag': node.name,
                'name': name,
                'type': node.get('type') or '',
                'value': node.get('value') or '',
            }
            if node.name == 'select':
                item['options'] = [
                    {'value': opt.get('value') or '', 'label': _clean(opt.get_text(' ', strip=True))}
                    for opt in node.find_all('option')[:20]
                ]
            controls.append(item)
        forms.append({
            'method': (form.get('method') or 'get').lower(),
            'action': urljoin(base_url, form.get('action') or base_url),
            'controls': controls[:80],
        })

    tables = []
    for table in soup.find_all('table')[:8]:
        headers = [_clean(x.get_text(' ', strip=True)) for x in table.find_all('th')]
        rows = []
        for tr in table.find_all('tr')[:5]:
            cells = [_clean(x.get_text(' ', strip=True)) for x in tr.find_all(['td', 'th'])]
            if cells:
                rows.append(cells[:20])
        tables.append({'headers': headers[:20], 'rows': rows})

    links = []
    for a in soup.find_all('a', href=True):
        label = _clean(a.get_text(' ', strip=True))
        href = urljoin(base_url, a['href'])
        hay = (label + ' ' + href).lower()
        if any(word in hay for word in ('permit', 'search', 'report')):
            links.append({'label': label, 'href': href})
        if len(links) >= 30:
            break

    return {
        'title': _clean(soup.title.get_text(' ', strip=True) if soup.title else ''),
        'forms': forms,
        'tables': tables,
        'links': links,
    }


class CaldwellCitizenserveDiscoveryCollector:
    name = 'Caldwell'
    landing_url = SEARCH_URL

    def collect(self):
        session = requests.Session()
        session.headers.update(BROWSER_HEADERS)
        home = session.get(HOME_URL, timeout=45, allow_redirects=True)
        home.raise_for_status()
        response = session.get(SEARCH_URL, timeout=60, allow_redirects=True, headers={'Referer': home.url})
        response.raise_for_status()
        summary = summarize_search_page(response.text, response.url)
        raise RuntimeError(f'Citizenserve discovery only; final_url={response.url}; summary={summary}')
