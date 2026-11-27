"""Additive reporting-only view; never mutates permit history or ranking."""
import json
from datetime import date, timedelta
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

CANYON_TRACKER = 'https://maps.canyonco.org/arcgisserver/rest/services/DSD/Building_Permits_NEW_2023/FeatureServer/1'
UNIX_DAY = date(1970, 1, 1)
MILLIS_PER_DAY = 86_400_000


def canyon_utc_civil(raw, today):
    # County layer /1 date metadata is UTC, and published source dates match
    # UTC-midnight encodings. These are civil dates, not Boise timestamps.
    if type(raw) is not int or raw <= 0 or raw % MILLIS_PER_DAY:
        return None
    days = raw // MILLIS_PER_DAY
    if not (date(2000, 1, 1) - UNIX_DAY).days <= days <= (today - UNIX_DAY).days:
        return None
    return UNIX_DAY + timedelta(days=days)


def canyon_issue_evidence(status, observations, today):
    # Aggregate current source evidence only. Never emit identities/raw data or
    # write back to an application's stage, published rows, or lead policy.
    if status.get('status') != 'ok' or status.get('source_url') != CANYON_TRACKER:
        return None
    distinct = {}
    for p in observations:
        raw = p.raw
        if (p.source_name != 'Canyon County DSD Building Permit Tracker'
                or p.source_url != CANYON_TRACKER or p.jurisdiction != 'Canyon County'
                or p.stage != 'APPLICATION' or not isinstance(raw, dict)
                or not p.permit_number or raw.get('BP_PermitNumber') != p.permit_number):
            return None  # scope or identity not verified
        if p.key in distinct and distinct[p.key] != raw:
            return None  # conflicting source identities aren't comparable evidence
        distinct[p.key] = raw
    if not distinct or status.get('records_seen') != len(observations):
        return None  # no proof of a complete county issued inventory
    issue_dates = []
    for raw in distinct.values():
        d = canyon_utc_civil(raw.get('PermitIssuedDate'), today)
        receipt = canyon_utc_civil(raw.get('BP_ReceivedDate'), today)
        if (raw.get('PemitIssued') == 'Permit Issued' and d is not None
                and (receipt is not None or raw.get('BP_ReceivedDate') is None)
                and (receipt is None or d >= receipt)):
            issue_dates.append(d)
    return {
        'schema_version': 1, 'source_url': CANYON_TRACKER,
        'scope': 'observed_active_application_tracker_rows',
        'applications_examined': len(distinct),
        'explicit_issue_observations': len(issue_dates),
        'latest_explicit_issue_date': max(issue_dates).isoformat() if issue_dates else None,
    }


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
        report_date=validated(status.get('latest_issued_date'),today) if name in {'Meridian','Nampa','Post Falls'} else None
        has_evidence=bool(observed or report_date)
        partial=state in {'degraded','stale'} and has_evidence
        succeeded=state=='ok' and has_evidence
        # Meridian index discovery may fail while its official direct PDFs give
        # a successful current data collection. Never call the index healthy or
        # move the comparable baseline for partial discovery.
        verified_fallback=name=='Meridian' and partial and bool(observed and report_date)
        data_success=succeeded or verified_fallback
        if succeeded:
            availability,outcome='reachable','success'
        elif partial:
            availability,outcome='partial','unknown'
        elif state=='error':
            availability,outcome='unavailable','error'
        else:
            availability,outcome='unknown','unknown'
        retained_rows={p.key:p for p in permits if p.source_name in source_names}
        retained=len(retained_rows)
        retained_date=max((d for p in retained_rows.values() if (d:=authoritative_date(name,p,today))),default=None) if name=='Post Falls' else None
        dates=[d for p in observed.values() if (d:=authoritative_date(name,p,today))]
        if report_date:
            dates.append(report_date)
        current=max(dates,default=None) if succeeded or partial else None
        prior_success_date=validated(old.get('last_successful_authoritative_date'),today)
        last_success_date=max((d for d in (prior_success_date,current if data_success else None) if d),default=None)
        latest=max((d for d in (current,prior_success_date) if d),default=None)
        comparable=succeeded and bool(old.get('last_success_at')) and old.get('comparable_success_baseline') is True and original_ids is not None
        rows.append(dict(id=ident,label=label,mode='automatic',coverage=COVERAGE[name],
            last_attempt_at=now,last_success_at=now if data_success else old.get('last_success_at'),
            verified_data_fallback=verified_fallback,
            retained_latest_authoritative_date=retained_date.isoformat() if retained_date else None,
            latest_authoritative_date=latest.isoformat() if latest else None,
            latest_date_kind=kind if latest else None,
            date_provenance=('current_report' if latest==current else 'prior_success') if latest else None,
            last_successful_authoritative_date=last_success_date.isoformat() if last_success_date else None,
            comparable_success_baseline=succeeded or (not partial and original_ids is not None and old.get('comparable_success_baseline') is True),
            source_age_days=(today-latest).days if latest else None,
            freshness_status=('stale' if state=='stale' or (name=='Post Falls' and current and (today-current).days>14) else None),
            new_since_previous_success=len(observed.keys()-original_ids) if comparable else None,
            retained_records=retained,observed_records=len(observed) if observed and (succeeded or partial) else None,
            availability=availability,collection_outcome=outcome))
        if name=='Canyon County':
            rows[-1]['issued_evidence']=canyon_issue_evidence(status, observations.get(name, ()), today)
    for ident,label,mode,coverage in EASTERN_GAPS:
        rows.append(dict(id=ident,label=label,mode=mode,coverage=coverage,
            last_attempt_at=None,last_success_at=None,latest_authoritative_date=None,latest_date_kind=None,
            source_age_days=None,new_since_previous_success=None,retained_records=None,observed_records=None,
            availability='not_attempted',collection_outcome='manual_only' if mode=='manual' else 'unknown'))
    return dict(schema_version=1,generated_at=now,sources=rows)
