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


def build_blank_permit_search(html: str, base_url: str = SEARCH_URL):
    soup = BeautifulSoup(html, 'html.parser')
    target = None
    for form in soup.find_all('form'):
        action = form.find('input', attrs={'name': 'Action'})
        if action and (action.get('value') or '') == 'DisplayCasesNPagging':
            target = form
            break
    if target is None:
        raise RuntimeError('Citizenserve search form not found')

    payload = {}
    for node in target.find_all(['input', 'select', 'textarea']):
        name = node.get('name')
        if not name:
            continue
        if node.name == 'select':
            selected = node.find('option', selected=True) or node.find('option')
            payload[name] = (selected.get('value') if selected else '') or ''
            continue
        input_type = (node.get('type') or '').lower()
        if input_type in {'checkbox', 'radio'} and not node.has_attr('checked'):
            continue
        payload[name] = node.get('value') or ''

    payload.update({
        'Action': 'DisplayCasesNPagging',
        'filetype': 'Permit',
        'StartIndex': '0',
        'EndIndex': '30',
    })
    return urljoin(base_url, target.get('action') or base_url), payload


def summarize_result_page(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    for tr in soup.find_all('tr'):
        cells = [_clean(x.get_text(' ', strip=True)) for x in tr.find_all(['td', 'th'])]
        cells = [x for x in cells if x]
        if len(cells) < 2:
            continue
        links = [
            {'label': _clean(a.get_text(' ', strip=True)), 'href': urljoin(base_url, a.get('href') or '')}
            for a in tr.find_all('a', href=True)
        ]
        rows.append({'cells': cells[:20], 'links': links[:8]})
        if len(rows) >= 30:
            break

    links = []
    for a in soup.find_all('a', href=True):
        label = _clean(a.get_text(' ', strip=True))
        href = urljoin(base_url, a['href'])
        hay = (label + ' ' + href).lower()
        if any(word in hay for word in ('permit', 'case', 'workorder', 'detail', 'view')):
            links.append({'label': label, 'href': href})
        if len(links) >= 50:
            break

    return {
        'title': _clean(soup.title.get_text(' ', strip=True) if soup.title else ''),
        'rows': rows,
        'links': links,
        'text': _clean(soup.get_text(' ', strip=True))[:6000],
    }


class CaldwellCitizenserveDiscoveryCollector:
    name = 'Caldwell'
    landing_url = SEARCH_URL

    def collect(self):
        session = requests.Session()
        session.headers.update(BROWSER_HEADERS)
        home = session.get(HOME_URL, timeout=45, allow_redirects=True)
        home.raise_for_status()
        search = session.get(SEARCH_URL, timeout=60, allow_redirects=True, headers={'Referer': home.url})
        search.raise_for_status()
        action, payload = build_blank_permit_search(search.text, search.url)
        response = session.post(action, data=payload, timeout=60, allow_redirects=True, headers={'Referer': search.url})
        response.raise_for_status()
        safe_payload = {k: v for k, v in payload.items() if k != 'uniqueID'}
        summary = summarize_result_page(response.text, response.url)
        raise RuntimeError(
            f'Citizenserve result probe only; final_url={response.url}; payload={safe_payload}; summary={summary}'
        )
