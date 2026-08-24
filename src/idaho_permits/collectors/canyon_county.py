from __future__ import annotations
from datetime import datetime, timezone
import re
import requests
from .base import CollectorResult
from ..models import Permit

LAYER_URL = 'https://maps.canyonco.org/arcgisserver/rest/services/DSD/Building_Permits_NEW_2023/FeatureServer/1'
QUERY_URL = LAYER_URL + '/query'
PAGE_SIZE = 1000
REQUIRED_FIELDS = {
    'BP_PermitNumber','BP_ProjectInfo','BP_SubType','BP_Classficiation',
    'BP_BuildValuation','BP_Address','BP_Contractor','BP_Status',
    'BP_ReceivedDate','BP_Approval_Status','BP_DecisionDate','BP_DateClosed',
    'BP_ParcelNumber'
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


def permit_from_tracker_attributes(a: dict) -> Permit | None:
    permit_number = str(a.get('BP_PermitNumber') or '').strip()
    received_date = _date(a.get('BP_ReceivedDate'))
    status = str(a.get('BP_Status') or '').strip()
    approval = str(a.get('BP_Approval_Status') or '').strip()
    if not permit_number or not received_date:
        return None
    if status.lower() != 'active' or approval.lower() not in {'in progress', 'approved'}:
        return None

    classification = str(a.get('BP_Classficiation') or '').strip()
    subtype = str(a.get('BP_SubType') or '').strip()
    project = str(a.get('BP_ProjectInfo') or '').strip()
    permit_type = ' | '.join(x for x in (subtype, classification) if x) or 'Building Application'
    return Permit(
        state='ID',
        jurisdiction='Canyon County',
        permit_number=permit_number,
        issued_date=received_date,
        permit_type=permit_type,
        address=str(a.get('BP_Address') or '').strip(),
        source_name='Canyon County DSD Building Permit Tracker',
        source_url=LAYER_URL,
        project_name=project or None,
        building_use=project or classification or subtype or None,
        valuation=_money(a.get('BP_BuildValuation')),
        contractor=str(a.get('BP_Contractor') or '').strip() or None,
        apn=str(a.get('BP_ParcelNumber') or '').strip() or None,
        status=f'{status} / {approval}',
        county='Canyon',
        stage='APPLICATION',
        raw=a,
    )


class CanyonCountyPermitCollector:
    name = 'Canyon County'
    landing_url = LAYER_URL
    replace_jurisdiction = True

    def collect(self):
        meta = requests.get(LAYER_URL, params={'f':'json'}, timeout=45)
        meta.raise_for_status()
        metadata = meta.json()
        if metadata.get('error'):
            raise RuntimeError(f"ArcGIS metadata error: {metadata['error']}")
        layer_name = str(metadata.get('name') or '')
        normalized_name = re.sub(r'[^a-z]', '', layer_name.lower())
        fields = {str(f.get('name') or '') for f in (metadata.get('fields') or [])}
        missing = sorted(REQUIRED_FIELDS - fields)
        if 'buildingpermit' not in normalized_name or missing:
            raise RuntimeError(f'Unexpected Canyon County tracker identity name={layer_name!r} missing_fields={missing}')

        permits = []
        offset = 0
        while True:
            params = {
                'where': 'BP_PermitNumber IS NOT NULL AND BP_ReceivedDate IS NOT NULL',
                'outFields': '*',
                'returnGeometry': 'false',
                'f': 'json',
                'resultOffset': offset,
                'resultRecordCount': PAGE_SIZE,
                'orderByFields': 'BP_ReceivedDate DESC',
            }
            response = requests.get(QUERY_URL, params=params, timeout=60)
            response.raise_for_status()
            payload = response.json()
            if payload.get('error'):
                raise RuntimeError(f"ArcGIS query error: {payload['error']}")
            features = payload.get('features') or []
            for feature in features:
                permit = permit_from_tracker_attributes(feature.get('attributes') or {})
                if permit:
                    permits.append(permit)
            if len(features) < PAGE_SIZE:
                break
            offset += len(features)

        return CollectorResult(
            'Canyon County',
            LAYER_URL,
            permits,
            'Official Canyon County DSD current building-permit tracker; active applications only; date is application received date',
        )
