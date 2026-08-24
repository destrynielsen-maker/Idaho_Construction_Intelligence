from __future__ import annotations
from datetime import datetime, timezone
import requests
from .base import CollectorResult
from ..models import Permit

LAYER_URL = 'https://services1.arcgis.com/WHM6qC35aMtyAAlN/ArcGIS/rest/services/Development_Tracker_Open_Data/FeatureServer/0'
QUERY_URL = LAYER_URL + '/query'
PAGE_SIZE = 2000


def _date(value):
    if value in (None, ''):
        return ''
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    text = str(value).strip()
    if len(text) >= 10 and text[4] == '-' and text[7] == '-':
        return text[:10]
    return text


def permit_from_feature(feature: dict) -> Permit | None:
    a = feature.get('attributes') or {}
    record_id = str(a.get('RecordID') or '').strip()
    if not record_id:
        return None
    record_type = str(a.get('RecordType') or 'Planning').strip()
    description = str(a.get('Description') or '').strip()
    record_name = str(a.get('RecordName') or '').strip()
    website = str(a.get('Website') or '').strip() or LAYER_URL
    return Permit(
        state='ID',
        jurisdiction='Boise',
        permit_number=record_id,
        issued_date=_date(a.get('AddToTrackerDate')),
        permit_type=f'Planning - {record_type}',
        address=str(a.get('PropertyAddress') or '').strip(),
        source_name='Boise Development Tracker',
        source_url=website,
        project_name=record_name or None,
        building_use=description or None,
        area=str(a.get('ComprehensivePlanningArea') or '').strip() or None,
        status=str(a.get('Status') or '').strip() or None,
        city='Boise',
        county='Ada',
        stage='PLANNING',
        raw=a,
    )


class BoiseDevelopmentCollector:
    name = 'Boise'
    landing_url = LAYER_URL

    def collect(self):
        permits = []
        offset = 0
        while True:
            params = {
                'where': '1=1',
                'outFields': '*',
                'returnGeometry': 'false',
                'f': 'json',
                'resultOffset': offset,
                'resultRecordCount': PAGE_SIZE,
                'orderByFields': 'AddToTrackerDate DESC',
            }
            response = requests.get(QUERY_URL, params=params, timeout=45)
            response.raise_for_status()
            payload = response.json()
            if payload.get('error'):
                raise RuntimeError(f"ArcGIS error: {payload['error']}")
            features = payload.get('features') or []
            for feature in features:
                permit = permit_from_feature(feature)
                if permit:
                    permits.append(permit)
            if len(features) < PAGE_SIZE:
                break
            offset += len(features)
        return CollectorResult(
            'Boise',
            LAYER_URL,
            permits,
            'Official City of Boise Development Tracker active planning projects; daily early-lead source',
        )
