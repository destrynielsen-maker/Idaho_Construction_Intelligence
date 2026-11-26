"""Additive reporting-only view; never mutates permit history or ranking."""
import json
from datetime import date
from pathlib import Path

SOURCES = {
    'Boise': ('boise-planning', 'Boise Development Tracker', 'planning', {'Boise Development Tracker'}),
    'Boise Issued Building Permits': ('boise-issued', 'Boise Issued Building Permits', 'issued', {'City of Boise Accela Citizen Access'}),
    'Eagle': ('eagle', 'Eagle', 'issued', {'Eagle iWorQ Permit Portal'}),
    'Canyon County': ('canyon-county', 'Canyon County', 'application', {'Canyon County DSD Building Permit Tracker'}),
    'Caldwell': ('caldwell', 'Caldwell', 'planning', {'COMPASS Development Review'}),
    "Coeur d'Alene": ('coeur-dalene', "Coeur d’Alene", 'issued', {"Coeur d'Alene Issued Permits"}),
    'Kootenai County': ('kootenai-county', 'Kootenai County', 'issued', {'Kootenai County weekly building permit report'}),
    'Post Falls': ('post-falls', 'Post Falls', 'issued', {'City of Post Falls Building Permits GIS'}),
    'Meridian': ('meridian', 'Meridian', 'issued', {'Meridian permit report'}),
    'Nampa': ('nampa', 'Nampa', 'issued', {'Nampa weekly permit activity report','Nampa permit report'}),
}

COVERAGE = {
    'Boise': 'City of Boise · development tracker',
    'Boise Issued Building Permits': 'City of Boise · building permits',
    'Eagle': 'City of Eagle · building permits',
    'Canyon County': 'Unincorporated Canyon County · county permits',
    'Caldwell': 'Caldwell · regional development review',
    "Coeur d'Alene": 'City of Coeur d’Alene · building permits',
    'Kootenai County': 'Unincorporated Kootenai County · weekly permit reports',
    'Post Falls': 'City of Post Falls · rolling 90-day building permit window',
    'Meridian': 'City of Meridian · building permit reports',
    'Nampa': 'City of Nampa · weekly building permit reports',
}
EASTERN_GAPS = (
    ('bingham-manual', 'Bingham County', 'manual', 'Bingham County · official reports require manual review; not collected here'),
    ('eastern-idaho-issued-gap', 'Eastern Idaho coverage gaps', 'uncovered',
     'Idaho Falls, Rexburg, Pocatello and Blackfoot city-issued permits not collected here'),
)

def prior_status(path: Path):
    try:
        prev=json.loads(path.read_text(encoding='utf-8')).get('reporting_v1',{})
        return {r['id']:r for r in prev.get('sources',[]) if r.get('id')} if prev.get('schema_version')==1 else {}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}

def validated(raw, today):
    if not isinstance(raw,str):
        return None
    try:
        d=date.fromisoformat(raw)
        return d if d.isoformat()==raw and d<=today else None
    except ValueError:
        return None

def authoritative_date(name,p,today):
    if name not in SOURCES or p.source_name not in SOURCES[name][3]:
        return None
    raw=p.raw or {}
    # Eagle/Boise legacy dates were not uniformly verified; require exact row flags.
    if name=='Eagle' and raw.get('issue_date_verified') is not True:
        return None
    if name=='Boise Issued Building Permits' and raw.get('source_issue_date_authoritative') is not True:
        return None
    if name in {'Boise','Caldwell','Nampa'}:
        # Historical planning placeholders and Nampa legacy PDFs must not set freshness.
        return None
    return validated(p.issued_date,today)

def reporting_report(statuses, observations, permits, original_ids, previous, now):
    today=date.fromisoformat(now[:10]); rows=[]
    for status in statuses:
        name=status['source']
        if name not in SOURCES:
            continue
        ident,label,kind,source_names=SOURCES[name]
        old=previous.get(ident,{})
        observed={p.key:p for p in observations.get(name,()) if p.source_name in source_names}
        state=str(status.get('status','error')).lower()
        report_date=validated(status.get('latest_issued_date'),today) if name in {'Meridian','Nampa'} else None
        has_evidence=bool(observed or report_date)
        partial=state in {'degraded','stale'} and has_evidence
        succeeded=state=='ok' and has_evidence
        if succeeded:
            availability,outcome='reachable','success'
        elif partial:
            availability,outcome='partial','unknown'
        elif state=='error':
            availability,outcome='unavailable','error'
        else:
            availability,outcome='unknown','unknown'
        retained=len({p.key for p in permits if p.source_name in source_names})
        dates=[d for p in observed.values() if (d:=authoritative_date(name,p,today))]
        if report_date:
            dates.append(report_date)
        current=max(dates,default=None) if succeeded or partial else None
        prior_success_date=validated(old.get('last_successful_authoritative_date'),today)
        last_success_date=max((d for d in (prior_success_date,current if succeeded else None) if d),default=None)
        latest=max((d for d in (current,prior_success_date) if d),default=None)
        comparable=succeeded and bool(old.get('last_success_at')) and old.get('comparable_success_baseline') is True and original_ids is not None
        rows.append(dict(id=ident,label=label,mode='automatic',coverage=COVERAGE[name],
            last_attempt_at=now,last_success_at=now if succeeded else old.get('last_success_at'),
            latest_authoritative_date=latest.isoformat() if latest else None,
            latest_date_kind=kind if latest else None,
            date_provenance=('current_report' if latest==current else 'prior_success') if latest else None,
            last_successful_authoritative_date=last_success_date.isoformat() if last_success_date else None,
            comparable_success_baseline=succeeded or (not partial and original_ids is not None and old.get('comparable_success_baseline') is True),
            source_age_days=(today-latest).days if latest else None,
            new_since_previous_success=len(observed.keys()-original_ids) if comparable else None,
            retained_records=retained,observed_records=len(observed) if observed and (succeeded or partial) else None,
            availability=availability,collection_outcome=outcome))
    for ident,label,mode,coverage in EASTERN_GAPS:
        rows.append(dict(id=ident,label=label,mode=mode,coverage=coverage,
            last_attempt_at=None,last_success_at=None,latest_authoritative_date=None,latest_date_kind=None,
            source_age_days=None,new_since_previous_success=None,retained_records=None,observed_records=None,
            availability='not_attempted',collection_outcome='manual_only' if mode=='manual' else 'unknown'))
    return dict(schema_version=1,generated_at=now,sources=rows)
