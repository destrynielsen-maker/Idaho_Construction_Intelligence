from __future__ import annotations
from datetime import datetime, timezone
import re
import requests
from .base import CollectorResult
from ..models import Permit

LAYER_URL = 'https://maps.canyonco.org/arcgisserver/rest/services/DSD/DSD_BLDG_PERMITS/FeatureServer/0'
QUERY_URL = LAYER_URL + '/query'
PAGE_SIZE = 1000
REQUIRED_FIELDS = {
    'PermitIssued','PermitNum','Classification','Address','ProjectInfo',
    'Contractor','Subdivision','Valuation','Status','ParcelNum1'
}


def _date(value):
    if value in (None, ''):
        return ''
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    text = str(value).strip()
    if len(text) >= 10 and text[4] == '-' and text[7] == '-':
        return text[:10]
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
    if m:
        month, day, year = map(int, m.groups())
        return f'{year:04d}-{month:02d}-{day:02d}'
    return text


def _money(value):
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r'[^0-9.\-]', '', str(value))
    try:
        return float(text) if text else None
    except ValueError:
        return None


def permit_from_attributes(a: dict) -> Permit | None:
    permit_number = str(a.get('PermitNum') or '').strip()
    issued_date = _date(a.get('PermitIssued'))
    if not permit_number or not issued_date:
        return None
    classification = str(a.get('Classification') or '').strip()
    project = str(a.get('ProjectInfo') or '').strip()
    address = str(a.get('Address') or '').strip()
    contractor = str(a.get('Contractor') or '').strip()
    return Permit(
        state='ID',
        jurisdiction='Canyon County',
        permit_number=permit_number,
        issued_date=issued_date,
        permit_type=classification or 'Building Permit',
        address=address,
        source_name='Canyon County DSD Building Permits',
        source_url=LAYER_URL,
        project_name=project or None,
        building_use=project or classification or None,
        valuation=_money(a.get('Valuation')),
        contractor=contractor or None,
        apn=str(a.get('ParcelNum1') or '').strip() or None,
        status=str(a.get('Status') or '').strip() or None,
        subdivision=str(a.get('Subdivision') or '').strip() or None,
        county='Canyon',
        stage='PERMITTED',
        raw=a,
    )


class CanyonCountyPermitCollector:
    name = 'Canyon County'
    landing_url = LAYER_URL

    def collect(self):
        meta = requests.get(LAYER_URL, params={'f':'json'}, timeout=45)
        meta.raise_for_status()
        metadata = meta.json()
        if metadata.get('error'):
            raise RuntimeError(f"ArcGIS metadata error: {metadata['error']}")
        layer_name = str(metadata.get('name') or '')
        fields = {str(f.get('name') or '') for f in (metadata.get('fields') or [])}
        missing = sorted(REQUIRED_FIELDS - fields)
        if 'building permit' not in layer_name.lower() or missing:
            raise RuntimeError(f'Unexpected Canyon County layer identity name={layer_name!r} missing_fields={missing}')

        permits = []
        offset = 0
        while True:
            params = {
                'where': 'PermitNum IS NOT NULL AND PermitIssued IS NOT NULL',
                'outFields': '*',
                'returnGeometry': 'false',
                'f': 'json',
                'resultOffset': offset,
                'resultRecordCount': PAGE_SIZE,
                'orderByFields': 'PermitIssued DESC',
            }
            response = requests.get(QUERY_URL, params=params, timeout=60)
            response.raise_for_status()
            payload = response.json()
            if payload.get('error'):
                raise RuntimeError(f"ArcGIS query error: {payload['error']}")
            features = payload.get('features') or []
            for feature in features:
                permit = permit_from_attributes(feature.get('attributes') or {})
                if permit:
                    permits.append(permit)
            if len(features) < PAGE_SIZE:
                break
            offset += len(features)
        return CollectorResult(
            'Canyon County',
            LAYER_URL,
            permits,
            'Official Canyon County DSD issued-building-permit FeatureServer; explicit PermitIssued and PermitNum fields',
        )
