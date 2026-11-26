from __future__ import annotations
import os
from datetime import datetime,timezone
from pathlib import Path
from .classify import classify_permit
from .collectors.boise import BoiseDevelopmentCollector,BoiseIssuedPermitCollector
from .collectors.caldwell import CaldwellCompassCollector
from .collectors.canyon_county import CanyonCountyPermitCollector
from .collectors.coeur_dalene import CoeurDAleneCollector
from .collectors.eagle import EaglePermitCollector
from .collectors.kootenai_county import KootenaiCountyCollector
from .collectors.nampa import NampaPermitCollector
from .collectors.post_falls import PostFallsPermitCollector
from .collectors.report_pages import MeridianCollector
from .dashboard import write_public_data
from .feeds import write_all_feeds
from .reporting import prior_status, reporting_report
from .storage import load_permits,save_permits
COLLECTORS=[BoiseDevelopmentCollector(),BoiseIssuedPermitCollector(),EaglePermitCollector(),CanyonCountyPermitCollector(),CaldwellCompassCollector(),CoeurDAleneCollector(),KootenaiCountyCollector(),PostFallsPermitCollector(),MeridianCollector(),NampaPermitCollector()]

def _site_base_url():
    x=os.getenv('SITE_BASE_URL','').strip()
    if x:return x.rstrip('/')+'/'
    repo=os.getenv('GITHUB_REPOSITORY','')
    if '/' in repo:
        owner,name=repo.split('/',1); return f'https://{owner}.github.io/{name}/'
    return 'https://example.invalid/idaho-construction-intelligence/'

def run(root: Path):
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat(); store=root/'data'/'permits.json'; existing=load_permits(store); statuses=[]; total=0; observations={}; original_ids=set(existing); previous=prior_status(root/'public'/'data'/'sources.json')
    for c in COLLECTORS:
        try:
            r=c.collect()
            if getattr(c,'replace_jurisdiction',False):
                current_keys={p.key for p in r.permits}
                for key,old in list(existing.items()):
                    if old.jurisdiction==c.name and key not in current_keys:
                        del existing[key]
            total+=len(r.permits); qual=0
            for p in r.permits:
                classify_permit(p); qual+=int(p.qualifies); old=existing.get(p.key)
                # Eagle is append-only until historical reconciliation is separately approved.
                # A changed detail record must not remove or rewrite an already-published lead.
                if old and c.name==p.jurisdiction=='Eagle':
                    continue
                if old and c.name==p.jurisdiction=='Nampa':
                    # The current report does not establish ownership/design roles.
                    for field in ('owner','developer','architect'):
                        if getattr(p,field) is None:
                            setattr(p,field,getattr(old,field))
                p.first_seen_at=old.first_seen_at if old and old.first_seen_at else now; p.last_seen_at=now; existing[p.key]=p
            status={'source':r.source,'status':r.status,'records_seen':len(r.permits),'qualifying_records':qual,'source_url':r.source_url,'note':r.note}
            if r.latest_issued_date:status['latest_issued_date']=r.latest_issued_date
            if r.report_period_end:status['report_period_end']=r.report_period_end
            statuses.append(status); observations[r.source]=r.permits
        except Exception as e:
            statuses.append({'source':c.name,'status':'error','records_seen':0,'qualifying_records':0,'source_url':getattr(c,'pdf_url',getattr(c,'landing_url','')),'note':f'{type(e).__name__}: {e}'})
    permits=list(existing.values())
    for p in permits: classify_permit(p)
    save_permits(store,permits,now); write_public_data(root/'public',permits,statuses,now,reporting_report(statuses,observations,permits,original_ids,previous,now)); write_all_feeds(root/'public'/'feeds',permits,_site_base_url())
    return {'generated_at':now,'total_collected_this_run':total,'total_stored':len(permits),'qualifying_stored':sum(p.qualifies for p in permits),'sources':statuses}
