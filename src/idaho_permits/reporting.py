"""Additive reporting-only view; never mutates permit history or ranking."""
import json
from datetime import date
from pathlib import Path
from .collectors.canyon_progress import LAYER_URL as CANYON_TRACKER, canyon_utc_civil

SOURCES = {
    'Boise': ('boise-planning', 'Boise Development Tracker', 'planning', {'Boise Development Tracker'}),
    'Boise Issued Building Permits': ('boise-issued', 'Boise Issued Building Permits', 'issued', {'City of Boise Accela Citizen Access'}),
    'Ada County': ('ada-county-applications', 'Ada County Building Applications', 'application', set()),
    'Eagle': ('eagle', 'Eagle', 'issued', {'Eagle iWorQ Permit Portal','City of Eagle weekly building permit report'}),
    'Canyon County': ('canyon-county', 'Canyon County', 'application', {'Canyon County DSD Building Permit Tracker'}),
    'Caldwell': ('caldwell', 'Caldwell', 'planning', {'COMPASS Development Review'}),
    "Coeur d'Alene": ('coeur-dalene', "Coeur d’Alene", 'issued', {"Coeur d'Alene Issued Permits"}),
    'Kootenai County': ('kootenai-county', 'Kootenai County', 'issued', {'Kootenai County weekly building permit report'}),
    'Hayden': ('hayden', 'Hayden', 'issued', {'City of Hayden issued building permit report'}),
    'Twin Falls': ('twin-falls-city', 'City of Twin Falls', 'issued', {'City of Twin Falls monthly issued building permit report'}),
    'Jerome': ('jerome', 'City of Jerome', 'issued', {'City of Jerome monthly issued building permit report'}),
    'Post Falls': ('post-falls', 'Post Falls', 'issued', {'City of Post Falls Building Permits GIS'}),
    'Meridian': ('meridian', 'Meridian', 'issued', {'Meridian permit report'}),
    'Nampa': ('nampa', 'Nampa', 'issued', {'Nampa weekly permit activity report','Nampa permit report'}),
    'Garden City': ('garden-city', 'Garden City', 'issued', {'Garden City issued building permit CSV'}),
    'Hailey': ('hailey', 'Hailey', 'issued', {'City of Hailey detailed issued building permit report'}),
    'Blackfoot': ('blackfoot', 'Blackfoot', 'issued', {'City of Blackfoot issued building permit report'}),
    'Moscow': ('moscow', 'Moscow', 'issued', {'City of Moscow Monthly Building Permits Issued'}),
    'Bannock County': ('bannock-county', 'Bannock County', 'issued', {'Bannock County monthly issued building permits'}),
}

COVERAGE = {
    'Boise': 'City of Boise · development tracker',
    'Boise Issued Building Permits': 'City of Boise · building permits',
    'Ada County': 'Unincorporated Ada County · building application records',
    'Eagle': 'City of Eagle · building permits',
    'Canyon County': 'Unincorporated Canyon County · county permits',
    'Caldwell': 'Caldwell · regional development review',
    "Coeur d'Alene": 'City of Coeur d’Alene · building permits',
    'Kootenai County': 'Unincorporated Kootenai County · weekly permit reports',
    'Hayden': 'City of Hayden · monthly issued new homes, townhomes and commercial buildings',
    'Twin Falls': 'City of Twin Falls · monthly issued detached single-family homes',
    'Jerome': 'City of Jerome · monthly issued new single-family homes and commercial or industrial buildings',
    'Post Falls': 'City of Post Falls · rolling 90-day building permit window',
    'Meridian': 'City of Meridian · building permit reports',
    'Nampa': 'City of Nampa · weekly building permit reports',
    'Garden City': 'City of Garden City · issued new commercial and single-family buildings',
    'Hailey': 'City of Hailey · issued new buildings',
    'Blackfoot': 'City of Blackfoot · issued detached new homes',
    'Moscow': 'City of Moscow · issued new single-family and commercial buildings',
    'Bannock County': 'Bannock County · county-issued new single-family dwellings',
}
EASTERN_GAPS = (
    ('bingham-manual', 'Bingham County', 'manual', 'Bingham County · official reports require manual review; not collected here'),
    ('eastern-idaho-issued-gap', 'Eastern Idaho coverage gaps', 'uncovered',
     'Idaho Falls, Rexburg and Pocatello city-issued permits not collected here'),
)
EXPLICIT_REPORT_DATES = {'Meridian','Nampa','Post Falls','Eagle','Garden City','Hailey','Blackfoot','Moscow','Bannock County','Hayden','Twin Falls','Jerome'}

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
    if name in {'Twin Falls','Jerome'} and raw.get('issue_date_verified') is not True:
        return None
    if name=='Boise Issued Building Permits' and raw.get('source_issue_date_authoritative') is not True:
        return None
    if name in {'Boise','Caldwell','Nampa'}:
        # Historical planning placeholders and Nampa legacy PDFs must not set freshness.
        return None
    return validated(p.issued_date,today)

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
        report_date=validated(status.get('latest_issued_date'),today) if name in EXPLICIT_REPORT_DATES else None
        progress_only = status.get('progress_only') is True
        has_evidence=bool(observed or report_date)
        partial=state in {'degraded','stale'} and has_evidence
        succeeded=state=='ok' and has_evidence
        if progress_only:
            report_date = validated(status.get('latest_application_date'), today)
            succeeded = state == 'ok' and bool(status.get('progress_success_at'))
            partial = not succeeded and state != 'error' and bool(status.get('records_seen'))
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
        if progress_only:
            retained = status.get('progress_retained_records', old.get('retained_records'))
        retained_date=max((d for p in retained_rows.values() if (d:=authoritative_date(name,p,today))),default=None) if name=='Post Falls' else None
        dates=[d for p in observed.values() if (d:=authoritative_date(name,p,today))]
        if report_date:
            dates.append(report_date)
        current=max(dates,default=None) if succeeded or partial else None
        prior_success_date=validated(old.get('last_successful_authoritative_date'),today)
        last_success_date=max((d for d in (prior_success_date,current if data_success else None) if d),default=None)
        latest=max((d for d in (current,prior_success_date) if d),default=None)
        comparable=not progress_only and succeeded and bool(old.get('last_success_at')) and old.get('comparable_success_baseline') is True and original_ids is not None
        observed_count = len(observed) if observed else None
        if progress_only:
            observed_count = status.get('records_seen')
        rows.append(dict(id=ident,label=label,mode='automatic',coverage=COVERAGE[name],
            last_attempt_at=now,last_success_at=(status.get('progress_success_at') or now) if data_success else old.get('last_success_at'),
            verified_data_fallback=verified_fallback,
            retained_latest_authoritative_date=retained_date.isoformat() if retained_date else None,
            latest_authoritative_date=latest.isoformat() if latest else None,
            latest_date_kind=kind if latest else None,
            date_provenance=('current_report' if latest==current else 'prior_success') if latest else None,
            last_successful_authoritative_date=last_success_date.isoformat() if last_success_date else None,
            comparable_success_baseline=not progress_only and (succeeded or (not partial and original_ids is not None and old.get('comparable_success_baseline') is True)),
            source_age_days=(today-latest).days if latest else None,
            freshness_status=('stale' if state=='stale' or (name in {'Post Falls','Eagle'} and current and (today-current).days>14) else None),
            new_since_previous_success=len(observed.keys()-original_ids) if comparable else None,
            retained_records=retained,observed_records=observed_count if succeeded or partial else None,
            availability=availability,collection_outcome=outcome))
        if name=='Canyon County':
            rows[-1]['issued_evidence']=canyon_issue_evidence(status, observations.get(name, ()), today)
    for ident,label,mode,coverage in EASTERN_GAPS:
        rows.append(dict(id=ident,label=label,mode=mode,coverage=coverage,
            last_attempt_at=None,last_success_at=None,latest_authoritative_date=None,latest_date_kind=None,
            source_age_days=None,new_since_previous_success=None,retained_records=None,observed_records=None,
            availability='not_attempted',collection_outcome='manual_only' if mode=='manual' else 'unknown'))
    return dict(schema_version=1,generated_at=now,sources=rows)
