from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import requests

from .base import CollectorResult
from ..models import Permit

LAYER_URL = 'https://gis.postfalls.gov/server/rest/services/Building_Permits/FeatureServer/17'
QUERY_URL = LAYER_URL + '/query'
PAGE_SIZE = 500
MAX_PAGES = 5
WINDOW_DAYS = 90
STALE_AFTER_DAYS = 14

ACCEPTED_BUILDING_TYPES = {'Single-Family', 'Duplex', 'Townhouse', 'Multi-Family', 'Commercial'}
ACCEPTED_STATUSES = {'Active', 'Complete'}


def _date(value) -> str:
    if value in (None, ''):
        return ''
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    text = str(value).strip()
    return text[:10] if len(text) >= 10 and text[4] == '-' and text[7] == '-' else ''


def _number(value) -> float | None:
    try:
        return float(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def permit_from_attributes(a: dict, cutoff: date, today: date) -> Permit | None:
    number = str(a.get('USER_Record__') or '').strip()
    issued = _date(a.get('USER_Permit_License_Issued_Date'))
    if not number or not issued:
        return None
    issued_date = date.fromisoformat(issued)
    if issued_date < cutoff or issued_date > today:
        return None

    work_type = str(a.get('USER_Type_of_Work') or '').strip()
    building_type = str(a.get('USER_Building_Type') or '').strip()
    record_type = str(a.get('USER_Record_Type') or '').strip()
    status = str(a.get('USER_Record_Status') or '').strip()
    if work_type != 'New Construction' or building_type not in ACCEPTED_BUILDING_TYPES or status not in ACCEPTED_STATUSES:
        return None

    residential = record_type == 'Residential Building Permit'
    commercial = record_type == 'Commercial Building Permit'
    if building_type == 'Commercial':
        if not commercial:
            return None
        permit_type = 'New Commercial Building'
        building_use = 'New construction commercial building'
        units = None
    elif building_type == 'Single-Family':
        if not residential:
            return None
        permit_type = 'New Single Family Residential'
        building_use = 'New construction single-family dwelling'
        units = 1
    elif building_type == 'Duplex':
        if not residential:
            return None
        permit_type = 'New Duplex Residential'
        building_use = 'New construction duplex'
        units = 2
    elif building_type == 'Townhouse':
        if not residential:
            return None
        permit_type = 'New Townhouse Residential'
        building_use = 'New construction townhouse'
        units = None
    else:
        if not residential:
            return None
        permit_type = 'New Multifamily Building'
        building_use = 'New construction multi-family building'
        units = None

    description = str(a.get('DESCRIPTION') or '').strip()
    return Permit(
        state='ID',
        jurisdiction='Post Falls',
        permit_number=number,
        issued_date=issued,
        permit_type=permit_type,
        address=str(a.get('USER_Location') or '').strip(),
        source_name='City of Post Falls Building Permits GIS',
        source_url=LAYER_URL,
        project_name=description or None,
        building_use=building_use,
        units=units,
        valuation=_number(a.get('USER_Valuation')),
        status=status,
        city='Post Falls',
        county='Kootenai',
        stage='PERMITTED',
        raw=a,
    )


class PostFallsPermitCollector:
    name = 'Post Falls'
    landing_url = LAYER_URL
    replace_jurisdiction = True
    window_days = WINDOW_DAYS

    def collect(self):
        today = date.today()
        cutoff = today - timedelta(days=self.window_days - 1)
        permits = []
        source_rows = 0
        newest = None

        for page in range(MAX_PAGES):
            params = {
                'where': 'USER_Permit_License_Issued_Date IS NOT NULL',
                'outFields': '*',
                'returnGeometry': 'false',
                'orderByFields': 'USER_Permit_License_Issued_Date DESC',
                'resultOffset': page * PAGE_SIZE,
                'resultRecordCount': PAGE_SIZE,
                'f': 'json',
            }
            response = requests.get(QUERY_URL, params=params, timeout=60)
            response.raise_for_status()
            payload = response.json()
            if payload.get('error'):
                raise RuntimeError(f"Post Falls ArcGIS error: {payload['error']}")
            features = payload.get('features') or []
            if not features:
                break

            page_dates = []
            for feature in features:
                a = feature.get('attributes') or {}
                issued = _date(a.get('USER_Permit_License_Issued_Date'))
                if issued:
                    issue_date = date.fromisoformat(issued)
                    page_dates.append(issue_date)
                    if issue_date <= today and (newest is None or issue_date > newest):
                        newest = issue_date
                    if cutoff <= issue_date <= today:
                        source_rows += 1
                permit = permit_from_attributes(a, cutoff, today)
                if permit:
                    permits.append(permit)

            if len(features) < PAGE_SIZE or (page_dates and min(page_dates) < cutoff):
                break
        else:
            raise RuntimeError('Post Falls ArcGIS query exceeded pagination safety cap')

        if not source_rows:
            raise RuntimeError(f'Post Falls ArcGIS returned no issued permit records in rolling {self.window_days}-day window')

        unique = {p.key: p for p in permits}
        age = (today - newest).days if newest else None
        note = (
            f'Official City of Post Falls Building Permits GIS; rolling {self.window_days}-day issued window; '
            f'{source_rows} source records inspected; {len(unique)} ground-up building permits kept'
        )
        if newest:
            note += f'; newest issued permit {newest.isoformat()} ({age} days old)'
            if age > STALE_AFTER_DAYS:
                note += f'; WARNING source is more than {STALE_AFTER_DAYS} days behind current date'
        return CollectorResult(self.name, LAYER_URL, list(unique.values()), note)
