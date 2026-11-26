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
        ident,label,coverage,source_names=SOURCES[name]
        old=previous.get(ident,{})
        observed={p.key:p for p in observations.get(name,()) if p.source_name in source_names}
        state=str(status.get('status','error')).lower()
        date_from_report=validated(status.get('latest_issued_date'),today) if name in {'Meridian','Nampa'} else None
        succeeded=state in {'ok','degraded','stale'} and bool(observed or date_from_report)
        # Count all stable keys in durable history, independently of this run's observations.
        retained=len({p.key for p in permits if p.source_name in source_names})
        dates=[d for p in observed.values() if (d:=authoritative_date(name,p,today))]
        if date_from_report:
            dates.append(date_from_report)
        last_date=validated(old.get('latest_authoritative_date'),today)
        latest=max([d for d in (max(dates,default=None) if succeeded else None,last_date) if d],default=None)
        rows.append(dict(id=ident,label=label,mode='automated',coverage=coverage,
            last_attempt_at=now,last_success_at=now if succeeded else old.get('last_success_at'),
            latest_authoritative_date=latest.isoformat() if latest else None,
            latest_date_kind=coverage if latest else None,
            source_age_days=(today-latest).days if latest else None,
            new_since_previous_success=len(observed.keys()-original_ids) if succeeded else None,
            retained_records=retained,observed_records=len(observed) if succeeded else None,
            availability=state,collection_outcome='observed' if succeeded else 'no_confirmed_observation'))
    return dict(schema_version=1,generated_at=now,sources=rows)
