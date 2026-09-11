from __future__ import annotations
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from .base import CollectorResult
from .common import get
from ..models import Permit

PORTAL_URL = 'https://portal.iworq.net/EAGLE/permits/600'
DETAIL_PATH_RE = re.compile(r'/EAGLE/permit/600/\d+$', re.IGNORECASE)
MAX_PAGES = 8

_SECTION_HEADINGS = {
    'permit information', 'property information', 'contractors', 'fees', 'payments',
    'letters', 'uploaded files', 'files', 'inspections', 'next steps', 'accessibility',
}


def _clean(value): return re.sub(r'\s+', ' ', (value or '').strip())

def _date(value):
    text=_clean(value); m=re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})',text)
    if not m:return text
    month,day,year=map(int,m.groups()); return f'{year:04d}-{month:02d}-{day:02d}'

def _number(value):
    text=_clean(value).replace(',','')
    try:return int(text)
    except (TypeError,ValueError):return None

def _lines(html):
    soup=BeautifulSoup(html,'html.parser'); return [_clean(x) for x in soup.stripped_strings if _clean(x)]

def _is_label_or_section(value):
    low=_clean(value).lower()
    return not low or low in _SECTION_HEADINGS or low.endswith(':')

def _label_value(lines,aliases):
    aliases=tuple(a.lower().rstrip(':') for a in aliases)
    for i,line in enumerate(lines):
        low=line.lower().strip(); base=low.rstrip(':')
        for alias in aliases:
            if base==alias and i+1<len(lines):
                value=_clean(lines[i+1])
                if not _is_label_or_section(value):return value
            if low.startswith(alias+':'):
                value=_clean(line.split(':',1)[1])
                if value:return value
    return ''

def _detail_scope_from_lines(lines):
    hits=[]
    for label in ('description','project description','scope of work','work description','type of work','project name','permit description','construction type'):
        value=_label_value(lines,(label,))
        if value and value not in hits:hits.append(value)
    return ' | '.join(hits)[:4000]

def _detail_scope(html):
    return _detail_scope_from_lines(_lines(html))

def _contractor_from_lines(lines):
    for i,line in enumerate(lines):
        if line.lower()!='contractors':continue
        for value in lines[i+1:i+8]:
            low=value.lower()
            if low in _SECTION_HEADINGS and low!='contractors':break
            if low in {'builder','general','contractor','electrical','mechanical','plumbing','water','hvac'}:continue
            if value.startswith(',') or low.startswith('primary contact:') or value.endswith(':'):continue
            company=re.sub(r'\s+-\s*$','',_clean(value)).strip()
            if company:return company
    return None

def _append_record(rows,seen,permit_number,issued_date,permit_type,address,status,detail_url,scope=''):
    permit_number=_clean(permit_number)
    if not permit_number or permit_number in seen:return False
    seen.add(permit_number)
    rows.append({'permit_number':permit_number,'issued_date':_date(issued_date),'permit_type':_clean(permit_type),'address':_clean(address),'status':_clean(status),'detail_url':detail_url,'scope':_clean(scope)})
    return True

def detail_links_from_shell(html,base_url=PORTAL_URL):
    soup=BeautifulSoup(html,'html.parser'); out=[]; seen=set()
    for a in soup.find_all('a',href=True):
        url=urljoin(base_url,a['href'])
        if DETAIL_PATH_RE.fullmatch(urlparse(url).path) and url not in seen:
            seen.add(url); out.append(url)
    return out

def record_from_detail(html,detail_url):
    lines=_lines(html); permit_number=_label_value(lines,('permit #','permit number','permit no'))
    if not permit_number:return None
    return {
        'permit_number':permit_number,
        'issued_date':_date(_label_value(lines,('date','permit date','issued date','issue date'))),
        'permit_type':_label_value(lines,('permit type','type')),
        'use_class':_label_value(lines,('use class',)),
        'address':_label_value(lines,('permit address','project address','site address','address')),
        'status':_label_value(lines,('status','permit status')),
        'detail_url':detail_url,
        'scope':_detail_scope_from_lines(lines),
        'contractor':_contractor_from_lines(lines),
        'subdivision':_label_value(lines,('subdivision',)),
        'living_area_sqft':_number(_label_value(lines,('living area sqft','living area sq ft'))),
        'garage_sqft':_number(_label_value(lines,('garage square feet','garage sqft'))),
        'covered_patio_sqft':_number(_label_value(lines,('covered patio sqft','covered patio sq ft'))),
    }

def permits_from_listing(html,base_url=PORTAL_URL):
    soup=BeautifulSoup(html,'html.parser'); rows=[]; seen=set()
    for row in soup.select('table tr'):
        cells=row.find_all('td')
        if len(cells)<5:continue
        link=cells[0].find('a',href=True) or row.find('a',href=True); detail_url=urljoin(base_url,link['href']) if link else base_url
        _append_record(rows,seen,cells[0].get_text(' ',strip=True),cells[1].get_text(' ',strip=True),cells[2].get_text(' ',strip=True),cells[3].get_text(' ',strip=True),cells[4].get_text(' ',strip=True),detail_url)
    links={}
    for a in soup.find_all('a',href=True):
        label=_clean(a.get_text(' ',strip=True))
        if re.fullmatch(r'\d{4,}',label):links.setdefault(label,urljoin(base_url,a['href']))
    text='\n'.join(_clean(x) for x in soup.stripped_strings if _clean(x))
    pattern=re.compile(r'Permit\s*#:\s*(\d{4,})\s+Date:\s*(\d{1,2}/\d{1,2}/\d{4})\s+Permit\s*Type:\s*(.*?)\s+Permit\s*Address:\s*(.*?)\s+Status:\s*(.*?)\s*(?=Inspection Request|Request An Inspection|View\b|Permit\s*#:|Accessibility\b|$)',re.I|re.S)
    for m in pattern.finditer(text):
        number,date,permit_type,address,status=m.groups(); _append_record(rows,seen,number,date,permit_type,address,status,links.get(number,base_url))
    return rows

class EaglePermitCollector:
    name='Eagle'; landing_url=PORTAL_URL
    def collect(self):
        all_rows={}; seen_detail_urls=set(); detail_failures=0; detail_unparsed=0; pages_read=0
        for page in range(1,MAX_PAGES+1):
            page_url=PORTAL_URL if page==1 else f'{PORTAL_URL}?page={page}'
            listing=get(page_url); pages_read+=1; before=len(all_rows)
            direct=permits_from_listing(listing.text,listing.url)
            for row in direct:all_rows.setdefault(row['permit_number'],row)
            if not direct:
                links=[u for u in detail_links_from_shell(listing.text,listing.url) if u not in seen_detail_urls]
                if not links:break
                for detail_url in links:
                    seen_detail_urls.add(detail_url)
                    try:
                        detail=get(detail_url,referer=listing.url); row=record_from_detail(detail.text,detail.url)
                    except Exception:
                        detail_failures+=1; continue
                    if not row:detail_unparsed+=1; continue
                    all_rows.setdefault(row['permit_number'],row)
            if len(all_rows)==before:break
        if not all_rows:
            raise RuntimeError(f'zero parsed after {pages_read} page(s); detail_failures={detail_failures}; detail_unparsed={detail_unparsed}')

        enriched_rows={}
        for original in all_rows.values():
            row=dict(original)
            detail_url=row.get('detail_url') or PORTAL_URL
            if DETAIL_PATH_RE.fullmatch(urlparse(detail_url).path):
                try:
                    detail=get(detail_url,referer=PORTAL_URL)
                    rich=record_from_detail(detail.text,detail.url)
                except Exception:
                    detail_failures+=1; rich=None
                if rich:
                    for key,value in rich.items():
                        if value not in (None,''):
                            row[key]=value
                elif not row.get('scope'):
                    detail_unparsed+=1
            permit_number=_clean(row.get('permit_number'))
            if not permit_number:continue
            enriched_rows[permit_number]=row

        permits=[]
        for row in enriched_rows.values():
            scope=row.get('scope') or ''
            use_class=row.get('use_class') or ''
            permits.append(Permit(
                state='ID',jurisdiction='Eagle',permit_number=row['permit_number'],issued_date=row['issued_date'],
                permit_type=row['permit_type'],address=row['address'],source_name='Eagle iWorQ Permit Portal',
                source_url=row['detail_url'],project_name=scope or None,building_use=use_class or scope or None,
                contractor=row.get('contractor') or None,status=row.get('status') or None,
                subdivision=row.get('subdivision') or None,city='Eagle',county='Ada',stage='PERMITTED',
                raw={
                    'listing':row,
                    'detail_scope':scope,
                    'use_class':use_class,
                    'living_area_sqft':row.get('living_area_sqft'),
                    'garage_sqft':row.get('garage_sqft'),
                    'covered_patio_sqft':row.get('covered_patio_sqft'),
                },
            ))
        note=f'Official City of Eagle iWorQ public permit portal; {pages_read} current page(s) crawled; detail-enriched Use Class identifies new-home building permits; shared classifier suppresses trade permits'
        if detail_failures:note+=f'; {detail_failures} detail request(s) unavailable'
        if detail_unparsed:note+=f'; {detail_unparsed} detail page(s) unparsed'
        return CollectorResult('Eagle',PORTAL_URL,permits,note)
