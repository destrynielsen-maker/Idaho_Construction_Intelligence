import json
from pathlib import Path
from .source_registry import SOURCES
from .classify import historical_eagle_candidate

def write_public_data(public_dir,permits,status,generated_at):
    d=public_dir/'data'; d.mkdir(parents=True,exist_ok=True)
    q=[p.to_dict() for p in permits if p.qualifies]
    q.sort(key=lambda x:(x['score'],x['issued_date']),reverse=True)
    (d/'permits.json').write_text(json.dumps({'generated_at':generated_at,'permits':q},indent=2),encoding='utf-8')
    builders={}
    for p in permits:
        if p.qualifies and p.contractor:
            b=builders.setdefault(p.contractor,{'contractor':p.contractor,'count':0,'score_total':0,'valuation_total':0})
            b['count']+=1;b['score_total']+=p.score;b['valuation_total']+=p.valuation or 0
    (d/'builders.json').write_text(json.dumps(sorted(builders.values(),key=lambda x:(x['score_total'],x['count']),reverse=True),indent=2),encoding='utf-8')
    (d/'sources.json').write_text(json.dumps({'generated_at':generated_at,'collector_status':status,'directory':SOURCES},indent=2),encoding='utf-8')

    historical=[{
        'jurisdiction':p.jurisdiction, 'legacy_reference':p.permit_number,
        'legacy_listing_date':p.issued_date, 'type_as_reported':p.permit_type,
        'address_as_reported':p.address, 'evidence_status':'unverified_historical',
    } for p in permits if historical_eagle_candidate(p)]
    historical.sort(key=lambda p:(p['legacy_listing_date'],p['legacy_reference']),reverse=True)
    (d/'eagle-research.json').write_text(json.dumps({
        'generated_at':generated_at, 'records':historical,
        'notice':'Historical listing dates and references are unverified. These are not issued permits or sales leads.',
        'source_url':'https://cityofeagle.org/1863/Building-Permit-Reports',
    },indent=2),encoding='utf-8')
