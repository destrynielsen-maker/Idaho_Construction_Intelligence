from __future__ import annotations
import os
from datetime import datetime,timezone
from pathlib import Path
from .classify import classify_permit
from .collectors.coeur_dalene import CoeurDAleneCollector
from .collectors.kootenai_county import KootenaiCountyCollector
from .collectors.report_pages import MeridianCollector,NampaCollector
from .dashboard import write_public_data
from .feeds import write_all_feeds
from .storage import load_permits,save_permits
COLLECTORS=[CoeurDAleneCollector(),KootenaiCountyCollector(),MeridianCollector(),NampaCollector()]

def _site_base_url():
    x=os.getenv('SITE_BASE_URL','').strip()
    if x:return x.rstrip('/')+'/'
    repo=os.getenv('GITHUB_REPOSITORY','')
    if '/' in repo:
        owner,name=repo.split('/',1); return f'https://{owner}.github.io/{name}/'
    return 'https://example.invalid/idaho-construction-intelligence/'

def run(root: Path):
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat(); store=root/'data'/'permits.json'; existing=load_permits(store); statuses=[]; total=0
    for c in COLLECTORS:
        try:
            r=c.collect(); total+=len(r.permits); qual=0
            for p in r.permits:
                classify_permit(p); qual+=int(p.qualifies); old=existing.get(p.key); p.first_seen_at=old.first_seen_at if old and old.first_seen_at else now; p.last_seen_at=now; existing[p.key]=p
            statuses.append({'source':r.source,'status':'ok','records_seen':len(r.permits),'qualifying_records':qual,'source_url':r.source_url,'note':r.note})
        except Exception as e:
            statuses.append({'source':c.name,'status':'error','records_seen':0,'qualifying_records':0,'source_url':getattr(c,'pdf_url',getattr(c,'landing_url','')),'note':f'{type(e).__name__}: {e}'})
    permits=list(existing.values())
    for p in permits: classify_permit(p)
    save_permits(store,permits,now); write_public_data(root/'public',permits,statuses,now); write_all_feeds(root/'public'/'feeds',permits,_site_base_url())
    return {'generated_at':now,'total_collected_this_run':total,'total_stored':len(permits),'qualifying_stored':sum(p.qualifies for p in permits),'sources':statuses}
