"""Narrow, append-only fallback for the official Nampa guest Civic Access form."""
import json
import os
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .base import CollectorResult
from ..models import Permit

SITE = 'https://nampaid-energovpub.tylerhost.net/Apps/SelfService'
NAME = 'City of Nampa Civic Access'
SEARCH_TYPE = 'Residential (New Single Family Dwelling, Townhouse, and/or Duplex)'
PROBE = Path(__file__).resolve().parents[3] / 'scripts/nampa_guest_preview/probe.cjs'

def enabled():
    return os.getenv('NAMPA_CSS_FALLBACK') == '1'

def parse_batch(payload, lo, hi):
    if payload.get('scope') != SEARCH_TYPE or payload.get('period') != {'lo':lo.isoformat(),'hi':hi.isoformat()}:
        raise ValueError('unverified Civic Access window')
    rows = payload.get('rows')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 25 or type(payload.get('count')) is not int or payload['count'] != len(rows):
        raise ValueError('incomplete Civic Access result set')
    permits, seen, urls = [], set(), set()
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError('invalid Civic Access record')
        n = r.get('id','')
        status = r.get('status','')
        stamp = r.get('issued','')
        address = r.get('address','')
        scope = r.get('description','')
        u = urlsplit(r.get('url',''))
        if (not isinstance(n,str) or not re.fullmatch(r'RES-\d+-20\d{2}',n) or n in seen
            or u.scheme != 'https' or u.netloc != 'nampaid-energovpub.tylerhost.net' or u.query
            or not re.fullmatch(r'/apps/selfservice(?:/NampaIDProd)?/?',u.path,re.I)
            or not re.fullmatch(r'/permit/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',u.fragment,re.I)
            or u.fragment.lower() in urls or status not in ('Issued','Finaled','Finalized') or r.get('type') != SEARCH_TYPE
            or not isinstance(address,str) or not address.strip() or len(address)>250
            or not isinstance(scope,str) or not 1 <= len(scope) <= 500
            or not isinstance(stamp,str) or not re.fullmatch(r'20\d{2}-\d{2}-\d{2}',stamp)
            or not lo <= date.fromisoformat(stamp) <= hi):
            raise ValueError('Civic Access record failed source or issuance validation')
        match=re.match(r'^\s*NEW\s+(SFD|SINGLE[- ]FAMILY|TOWN(?:HOUSE|HOME)|DUPLEX)\b',scope,re.I)
        if not match or re.search(r'\b(?:restor(?:e|ation)|fire damage|remodel|repair)\b',scope,re.I):
            raise ValueError('case scope does not establish ground-up housing')
        form=match[1].upper()
        kind=('New single-family dwelling' if form in ('SFD','SINGLE-FAMILY','SINGLE FAMILY')
              else 'New duplex' if form=='DUPLEX' else 'New townhome')
        c=r.get('contractor')
        if c is not None and (not isinstance(c,str) or not c.strip() or len(c)>200):
            raise ValueError('invalid contractor-company field')
        seen.add(n); urls.add(u.fragment.lower())
        permits.append(Permit('ID','Nampa',n,stamp,kind,address,NAME,u.geturl(),
            project_name=scope,contractor=c,city='Nampa',county='Canyon',status=status,
            stage='PERMITTED',raw={'scope':scope,'issue_date_verified':True,
                'contractor_role':'Registered Building Contractor' if c else None,
                'coverage':'Residential new dwelling search only','period_start':lo.isoformat(),'period_end':hi.isoformat()}))
    return CollectorResult('Nampa',SITE+'#/search',permits,
        'Civic Access fallback: issued residential new dwellings only; not a complete city permit report. '
        'Only explicitly registered contractor companies are reported. Valuation not available.',
        status='degraded',latest_issued_date=max(p.issued_date for p in permits),report_period_end=hi.isoformat())

def collect_css(today=None):
    hi = today or datetime.now(ZoneInfo('America/Boise')).date()
    lo = hi - timedelta(days=6)
    try:
        result = subprocess.run(['node',str(PROBE),lo.strftime('%m/%d/%Y'),hi.strftime('%m/%d/%Y'),'--full'],
                                timeout=150,capture_output=True,check=True)
        if not 1 <= len(result.stdout) <= 150000:
            raise ValueError('Civic Access output exceeded preview bounds')
        return parse_batch(json.loads(result.stdout),lo,hi)
    except (subprocess.SubprocessError, OSError, ValueError, TypeError, AttributeError) as e:
        raise RuntimeError('Civic Access fallback did not return a verified batch') from e
