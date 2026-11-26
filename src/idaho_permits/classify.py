from __future__ import annotations
import re
from dataclasses import replace
from .models import Permit

NEGATIVE = ('reroof','re-roof','roof','hvac','mechanical','plumbing','electrical','solar','sign','fence','pool','window','door replacement','tenant improvement','remodel','alteration','repair','demolition','moving pod','tree pruning','sidewalk','conversion','convert ','modification')
TRADE_PREFIXES = ('electrical ','mechanical ','plumbing ','water ','sewer ','gas ','fire sprinkler ','fire alarm ')
MULTI = ('multifamily','multi-family','apartment','condominium','townhome','town home','duplex','fourplex','triplex')
SINGLE = ('single family','single-family','new residence','new residential','new dwelling')
COMMERCIAL = ('commercial','shell building','warehouse','industrial','hotel','hospitality','mixed use','mixed-use','retail building','office building')
NEW = ('new ','new construction','ground up','ground-up','shell building','duplex w/garage','duplex with garage')

def _norm(v): return re.sub(r'\s+',' ',(v or '').strip()).lower()

def unverified_eagle_listing(p: Permit) -> bool:
    raw=p.raw or {}
    return p.jurisdiction=='Eagle' and 'listing' in raw and raw.get('issue_date_verified') is not True

def historical_eagle_candidate(p: Permit) -> bool:
    """Reproduce the previous lead gate on a copy, for the research view only."""
    return unverified_eagle_listing(p) and _classify_construction(replace(p)).qualifies

def classify_permit(p: Permit) -> Permit:
    # Historical Eagle listing Date was not an issuing event and shifted cells sometimes
    # produced non-permit keys. Keep those rows in history, but not in sales outputs.
    if unverified_eagle_listing(p):
        p.classification='OTHER'; p.qualifies=False; p.new_construction_confidence='LOW'; p.score=0; return p
    return _classify_construction(p)

def _classify_construction(p: Permit) -> Permit:
    permit_type=_norm(p.permit_type)
    text=_norm(' '.join(filter(None,[p.permit_type,p.building_use,p.project_name])))
    if any(permit_type.startswith(x) for x in TRADE_PREFIXES) or any(x in text for x in NEGATIVE):
        p.classification='OTHER'; p.qualifies=False; p.new_construction_confidence='HIGH'; p.score=0; return p
    if any(x in text for x in MULTI): p.classification='MULTIFAMILY'
    elif any(x in text for x in SINGLE): p.classification='SINGLE_FAMILY'
    elif any(x in text for x in COMMERCIAL): p.classification='COMMERCIAL'
    else: p.classification='OTHER'
    explicit_new=any(x in text for x in NEW)
    if p.classification=='MULTIFAMILY' and ('duplex' in text or 'townhome' in text or 'apartment' in text): explicit_new=True
    p.qualifies=p.classification!='OTHER' and explicit_new
    p.new_construction_confidence='HIGH' if p.qualifies else 'LOW'
    p.score=score_permit(p)
    return p

def score_permit(p):
    if not p.qualifies: return 0
    score={'MULTIFAMILY':40,'COMMERCIAL':30,'SINGLE_FAMILY':15}.get(p.classification,0)
    v=p.valuation or 0
    if v>=25_000_000: score+=20
    elif v>=10_000_000: score+=15
    elif v>=5_000_000: score+=10
    elif v>=1_000_000: score+=7
    elif v>=500_000: score+=5
    u=p.units or 0
    if u>=100: score+=20
    elif u>=50: score+=15
    elif u>=20: score+=10
    elif u>=5: score+=5
    if p.contractor and _norm(p.contractor) not in {'homeowner','owner/builder','owner-builder','business owner','tbd'}: score+=5
    return score
