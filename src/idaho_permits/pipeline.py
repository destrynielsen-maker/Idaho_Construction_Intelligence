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


def _verify_history(before, after):
    missing = set(before) - set(after)
    altered = [key for key, first_seen in before.items() if key in after and after[key].first_seen_at != first_seen]
    if missing or altered:
        raise RuntimeError(f"Permit history preservation gate failed: {len(missing)} missing IDs, {len(altered)} altered first-seen timestamps")
COLLECTORS=[BoiseDevelopmentCollector(),BoiseIssuedPermitCollector(),EaglePermitCollector(),CanyonCountyPermitCollector(),CaldwellCompassCollector(),CoeurDAleneCollector(),KootenaiCountyCollector(),PostFallsPermitCollector(),MeridianCollector(),NampaPermitCollector()]

def _site_base_url():
    x=os.getenv('SITE_BASE_URL','').strip()
    if x:return x.rstrip('/')+'/'
    repo=os.getenv('GITHUB_REPOSITORY','')
    if '/' in repo:
        owner,name=repo.split('/',1); return f'https://{owner}.github.io/{name}/'
    return 'https://example.invalid/idaho-construction-intelligence/'

def run(root: Path):
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat(); store=root/'data'/'permits.json'; existing=load_permits(store); statuses=[]; total=0; observations={}; original_ids=set(existing) if store.is_file() else None; historic_first_seen={key:p.first_seen_at for key,p in existing.items()}; previous=prior_status(root/'public'/'data'/'sources.json')
    for c in COLLECTORS:
        try:
            r=c.collect()
            # A current-only source observation is not a deletion instruction.
            # Omitted keys keep their historical row and last_seen timestamp;
            # the observation applied to reporting includes only returned rows.
            omitted_count = 0
            if getattr(c, 'replace_jurisdiction', False):
                current_keys = {p.key for p in r.permits}
                omitted_count = sum(p.jurisdiction == c.name and p.key not in current_keys for p in existing.values())
            total+=len(r.permits); qual=0
            for p in r.permits:
                classify_permit(p); qual+=int(p.qualifies); old=existing.get(p.key)
                # Eagle is append-only until historical reconciliation is separately approved.
                # A changed detail record must not remove or rewrite an already-published lead.
                if old and c.name==p.jurisdiction=='Eagle':
                    continue
                if old and c.name==p.jurisdiction=='Nampa':
                    # Narrow CSS evidence can add an ID, never replace prior full source evidence.
                    if p.source_name == 'City of Nampa Civic Access':
                        continue
                    # The current report does not establish ownership/design roles.
                    for field in ('owner','developer','architect'):
                        if getattr(p,field) is None:
                            setattr(p,field,getattr(old,field))
                p.first_seen_at=old.first_seen_at if old else now; p.last_seen_at=now; existing[p.key]=p
            status={'source':r.source,'status':r.status,'records_seen':len(r.permits),'qualifying_records':qual,'source_url':r.source_url,'note':r.note}
            if omitted_count:status['retained_not_observed_in_latest_pull']=omitted_count
            if r.latest_issued_date:status['latest_issued_date']=r.latest_issued_date
            if r.report_period_end:status['report_period_end']=r.report_period_end
            statuses.append(status); observations[r.source]=r.permits
        except Exception as e:
            statuses.append({'source':c.name,'status':'error','records_seen':0,'qualifying_records':0,'source_url':getattr(c,'pdf_url',getattr(c,'landing_url','')),'note':f'{type(e).__name__}: {e}'})
    permits=list(existing.values())
    for p in permits: classify_permit(p)
    _verify_history(historic_first_seen,existing)
    save_permits(store,permits,now); write_public_data(root/'public',permits,statuses,now,reporting_report(statuses,observations,permits,original_ids,previous,now)); write_all_feeds(root/'public'/'feeds',permits,_site_base_url())
    return {'generated_at':now,'total_collected_this_run':total,'total_stored':len(permits),'qualifying_stored':sum(p.qualifies for p in permits),'sources':statuses}
