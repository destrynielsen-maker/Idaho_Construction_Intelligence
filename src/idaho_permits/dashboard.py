import json
from pathlib import Path
from .source_registry import SOURCES

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
