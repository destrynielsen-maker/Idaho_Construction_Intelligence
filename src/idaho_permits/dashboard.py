import json
from pathlib import Path
from .source_registry import SOURCES

def write_public_data(public_dir,permits,status,generated_at,reporting=None):
    d=public_dir/'data'; d.mkdir(parents=True,exist_ok=True)
    q=[p.to_dict() for p in permits if p.qualifies]
    q.sort(key=lambda x:(x['score'],x['issued_date']),reverse=True)
    (d/'permits.json').write_text(json.dumps({'generated_at':generated_at,'permits':q},indent=2),encoding='utf-8')
    # Preserve the previously published order when score/count are exactly tied.
    # Reloading a sorted ledger must not reshuffle equally ranked builders.
    builder_path=d/'builders.json'
    previous=json.loads(builder_path.read_text(encoding='utf-8')) if builder_path.exists() else []
    positions={row['contractor']:i for i,row in enumerate(previous)}
    if len(positions)!=len(previous):
        raise ValueError('Duplicate builder identity in prior ranking')
    builders={}
    for p in permits:
        if p.qualifies and p.contractor:
            b=builders.setdefault(p.contractor,{'contractor':p.contractor,'count':0,'score_total':0,'valuation_total':0})
            b['count']+=1;b['score_total']+=p.score;b['valuation_total']+=p.valuation or 0
    ordered=sorted(builders.values(),key=lambda x:(positions.get(x['contractor'],len(positions)),x['contractor']))
    ordered.sort(key=lambda x:(x['score_total'],x['count']),reverse=True)
    builder_path.write_text(json.dumps(ordered,indent=2),encoding='utf-8')
    sources={'generated_at':generated_at,'collector_status':status,'directory':SOURCES}
    if reporting is not None:
        sources['reporting_v1']=reporting
    (d/'sources.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
