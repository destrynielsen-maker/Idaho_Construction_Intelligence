from __future__ import annotations
import re
from datetime import date, datetime
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from .base import CollectorResult
from .common import get
from ..models import Permit

PORTAL_URL = 'https://portal.iworq.net/EAGLE/permits/600'
DETAIL_PATH_RE = re.compile(r'/EAGLE/permit/600/\d+$', re.IGNORECASE)
MAX_PAGES = 8
MAX_DETAILS_PER_RUN = 120
PERMIT_NUMBER_RE = re.compile(r'\d{4,12}')
_PRE_ISSUE_OR_VOID = re.compile(
    r'acceptance|application|pending|submission|review|ready to issue|not issued|hold|withdraw|void|denied|cancel',
    re.IGNORECASE,
)
_BUILDER_ROLES = {'builder', 'general contractor', 'registered building contractor'}
_OTHER_ROLES = {'contractor', 'general', 'electrical', 'mechanical', 'plumbing', 'water', 'hvac', 'subcontractor'}

_SECTION_HEADINGS = {
    'permit information', 'property information', 'contractors', 'fees', 'payments',
    'letters', 'uploaded files', 'files', 'inspections', 'next steps', 'accessibility',
}


def _clean(value): return re.sub(r'\s+', ' ', (value or '').strip())

def _date(value):
    text=_clean(value)
    try:
        if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}',text):
            return datetime.strptime(text,'%m/%d/%Y').date().isoformat()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',text):
            return date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    return ''

def _is_issued(issued, status):
    return bool(issued and issued <= date.today().isoformat() and not _PRE_ISSUE_OR_VOID.search(status or ''))

def _portal_detail(url):
    host=urlparse(url)
    return (host.scheme=='https' and host.netloc=='portal.iworq.net'
            and DETAIL_PATH_RE.fullmatch(host.path) is not None)

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
    # Select only a plainly role-tagged builder/GC; generic contractor or trade order is not proof.
    candidates=set()
    for i,line in enumerate(lines):
        if line.lower().rstrip(':')!='contractors':continue
        section=[]
        for value in lines[i+1:]:
            if value.lower().rstrip(':') in _SECTION_HEADINGS:break
            section.append(value)
        for j,value in enumerate(section[:-1]):
            role=section[j+1].lower().rstrip(':')
            if role not in _BUILDER_ROLES:continue
            company=re.sub(r'\s+-\s*$','',_clean(value)).strip()
            if company and not _is_label_or_section(company) and not company.startswith(',') and company.lower() not in _BUILDER_ROLES|_OTHER_ROLES:
                candidates.add((company,role))
    companies={company for company,_ in candidates}
    if len(companies)!=1:return (None,None)
    role=next((role for role in ('registered building contractor','general contractor','builder') if any(x[1]==role for x in candidates)),None)
    return (next(iter(companies)),role)

def _append_record(rows,seen,permit_number,display_date,permit_type,address,status,detail_url,issued_date=''):
    permit_number=_clean(permit_number)
    if not PERMIT_NUMBER_RE.fullmatch(permit_number) or permit_number in seen or not _clean(permit_type) or not _clean(address):
        return False
    seen.add(permit_number)
    rows.append({'permit_number':permit_number,'display_date':_date(display_date),'issued_date':_date(issued_date),
                 'permit_type':_clean(permit_type),'address':_clean(address),'status':_clean(status),
                 'detail_url':detail_url if _portal_detail(detail_url) else PORTAL_URL,'scope':''})
    return True

def detail_links_from_shell(html,base_url=PORTAL_URL):
    soup=BeautifulSoup(html,'html.parser'); out=[]; seen=set()
    for a in soup.find_all('a',href=True):
        url=urljoin(base_url,a['href'])
        if _portal_detail(url) and url not in seen:
            seen.add(url); out.append(url)
    return out

def record_from_detail(html,detail_url):
    lines=_lines(html); permit_number=_label_value(lines,('permit #','permit number','permit no'))
    if not PERMIT_NUMBER_RE.fullmatch(permit_number):return None
    contractor,role=_contractor_from_lines(lines)
    return {
        'permit_number':permit_number,
        'issued_date':_date(_label_value(lines,('issued date','issue date','date issued'))),
        'display_date':_date(_label_value(lines,('date','permit date','application date'))),
        'permit_type':_label_value(lines,('permit type','type')),
        'use_class':_label_value(lines,('use class',)),
        'address':_label_value(lines,('permit address','project address','site address','address')),
        'status':_label_value(lines,('status','permit status')),
        'detail_url':detail_url,
        'scope':_detail_scope_from_lines(lines),
        'contractor':contractor,
        'contractor_role':role,
        'subdivision':_label_value(lines,('subdivision',)),
        'living_area_sqft':_number(_label_value(lines,('living area sqft','living area sq ft'))),
        'garage_sqft':_number(_label_value(lines,('garage square feet','garage sqft'))),
        'covered_patio_sqft':_number(_label_value(lines,('covered patio sqft','covered patio sq ft'))),
    }

def permits_from_listing(html,base_url=PORTAL_URL):
    soup=BeautifulSoup(html,'html.parser'); rows=[]; seen=set()
    for table in soup.select('table'):
        headings=[_clean(x.get_text(' ',strip=True)).lower().rstrip(':') for x in table.select('tr th')]
        def index(*aliases):
            return next((i for i,h in enumerate(headings) if h in aliases),None)
        indices={k:index(*labels) for k,labels in {
            'number':('permit #','permit number','permit no'),
            'display':('date','permit date','application date'),
            'issued':('issued date','issue date','date issued'),
            'type':('permit type','type'),
            'address':('permit address','site address','address'),
            'status':('status','permit status'),
        }.items()}
        if any(indices[k] is None for k in ('number','type','address','status')):continue
        for row in table.select('tr'):
            cells=row.find_all('td',recursive=False)
            if not cells or len(cells)<len(headings):continue
            link=cells[indices['number']].find('a',href=True)
            detail_url=urljoin(base_url,link['href']) if link else PORTAL_URL
            def value(key):
                i=indices[key]
                return cells[i].get_text(' ',strip=True) if i is not None else ''
            _append_record(rows,seen,value('number'),value('display'),value('type'),value('address'),value('status'),detail_url,value('issued'))
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
        all_rows={}; seen_detail_urls=set(); detail_cache={}; detail_failures=0; detail_unparsed=0; pages_read=0
        def detail_record(url, referer):
            nonlocal detail_failures, detail_unparsed
            if url not in detail_cache:
                if not _portal_detail(url) or len(detail_cache)>=MAX_DETAILS_PER_RUN:return None
                try:
                    response=get(url,referer=referer)
                    if not _portal_detail(response.url):
                        raise ValueError('unexpected Eagle detail destination')
                    detail_cache[url]=record_from_detail(response.text,response.url)
                    if not detail_cache[url]:detail_unparsed+=1
                except Exception:
                    detail_failures+=1; detail_cache[url]=None
            return detail_cache[url]
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
                    row=detail_record(detail_url,listing.url)
                    if not row:continue
                    all_rows.setdefault(row['permit_number'],row)
            if len(all_rows)==before:break
        if not all_rows:
            raise RuntimeError(f'zero parsed after {pages_read} page(s); detail_failures={detail_failures}; detail_unparsed={detail_unparsed}')

        enriched_rows={}
        for original in all_rows.values():
            row=dict(original)
            detail_url=row.get('detail_url') or PORTAL_URL
            if _portal_detail(detail_url) and row['permit_type'].lower() in {'building residential','building commercial'}:
                rich=detail_record(detail_url,PORTAL_URL)
                # A response for a different record is not evidence for this listing.
                if rich and rich['permit_number']==row['permit_number']:
                    for key,value in rich.items():
                        if value not in (None,''):
                            row[key]=value
            permit_number=_clean(row.get('permit_number'))
            if not permit_number:continue
            enriched_rows[permit_number]=row

        permits=[]
        for row in enriched_rows.values():
            scope=row.get('scope') or ''
            use_class=row.get('use_class') or ''
            if row['permit_type'].lower() not in {'building residential','building commercial'}:
                continue
            if not row.get('address') or not _is_issued(row.get('issued_date'),row.get('status')):
                continue
            permits.append(Permit(
                state='ID',jurisdiction='Eagle',permit_number=row['permit_number'],issued_date=row['issued_date'],
                permit_type=row['permit_type'],address=row['address'],source_name='Eagle iWorQ Permit Portal',
                source_url=row['detail_url'],project_name=scope or None,building_use=use_class or scope or None,
                contractor=row.get('contractor') or None,status=row.get('status') or None,
                subdivision=row.get('subdivision') or None,city='Eagle',county='Ada',stage='PERMITTED',
                raw={
                    'listing':row,
                    'detail_scope':scope,
                    'issue_date_verified':True,
                    'contractor_role':row.get('contractor_role'),
                    'use_class':use_class,
                    'living_area_sqft':row.get('living_area_sqft'),
                    'garage_sqft':row.get('garage_sqft'),
                    'covered_patio_sqft':row.get('covered_patio_sqft'),
                },
            ))
        if not permits:
            raise RuntimeError(f'Eagle listing accessible ({len(all_rows)} candidates) but no building row had a verified issue date; {detail_failures} unavailable, {detail_unparsed} unparsed detail pages')
        note=f'Official City of Eagle iWorQ; {pages_read} page(s), {len(all_rows)} listing candidates, {len(permits)} building records with explicit issue date; trades and unissued records excluded'
        if detail_failures:note+=f'; {detail_failures} detail request(s) unavailable'
        if detail_unparsed:note+=f'; {detail_unparsed} detail page(s) unparsed'
        return CollectorResult('Eagle',PORTAL_URL,permits,note)
