"""Track unincorporated Ada County building applications without inferring issuance."""

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import re
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from .base import CollectorResult


LAYER_URL = ('https://gisprodapi.adacounty.id.gov/arcgis/rest/services/'
             'DevelopmentServices/Planning_and_Building/MapServer/0')
QUERY_URL = LAYER_URL + '/query'
SOURCE_NAME = 'Ada County building application tracker'
WINDOW_DAYS = 90
PAGE_SIZE = 200
MAX_RECORDS = 1000
MOUNTAIN = ZoneInfo('America/Boise')
FIELDS = {
    'OBJECTID': 'esriFieldTypeOID',
    'APPFILE': 'esriFieldTypeString',
    'AppDivision': 'esriFieldTypeString',
    'STATUS': 'esriFieldTypeString',
    'APPStatus': 'esriFieldTypeString',
    'APPAprvlStatus': 'esriFieldTypeString',
    'APPRcvdDate': 'esriFieldTypeDate',
    'APPClosDate': 'esriFieldTypeDate',
}
DISPOSITION_CODES = {'active': 'A', 'closed': 'C', 'expired': 'E', 'void': 'V', 'withdrawn': 'W'}


def _get_json(url, **params):
    response = requests.get(url, params={'f': 'json', **params}, timeout=(5, 10), allow_redirects=False,
                            headers={'User-Agent': 'Idaho Construction Intelligence permit collector'})
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError('Unexpected Ada County REST response status')
    payload = response.json()
    if not isinstance(payload, dict) or 'error' in payload:
        raise ValueError('Ada County REST response did not contain usable evidence')
    return payload


def _civil(value, today, *, closure=False):
    if type(value) is not int or value <= 0:
        return None
    # APPClosDate is entered as a date and exported at UTC midnight. Receipt is
    # a timestamp, so preserve its civil date in the issuing county's timezone.
    if closure and value % 86_400_000 != 0:
        return None
    try:
        stamp = datetime.fromtimestamp(value / 1000, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    civil = stamp.date() if closure else stamp.astimezone(MOUNTAIN).date()
    return civil if date(2000, 1, 1) <= civil <= today else None


def _application(row, today, start):
    number = row.get('APPFILE')
    if row.get('AppDivision') != 'BL' or not isinstance(number, str) or not re.fullmatch(r'[0-9]{7}-BP', number):
        raise ValueError('Ada County row is outside the verified building application scope')

    received = _civil(row.get('APPRcvdDate'), today)
    closure = _civil(row.get('APPClosDate'), today, closure=True)
    if not received or (received < start and (not closure or closure < start)):
        raise ValueError('Ada County row lacks a verified receipt within the query scope')

    status, app_code, approval_code = (row.get(field) for field in ('STATUS', 'APPStatus', 'APPAprvlStatus'))
    if any(not isinstance(value, str) or not value.strip() or len(value) > 60
           or any(ord(char) < 32 for char in value) for value in (status, app_code, approval_code)):
        raise ValueError('Ada County row has invalid application status evidence')
    disposition = status.strip().lower()
    if DISPOSITION_CODES.get(disposition) != app_code:
        disposition = None
    closed = disposition == 'closed' and closure is not None and received <= closure
    query = urlencode({'where': f"APPFILE = '{number}' AND AppDivision = 'BL'", 'outFields': ','.join(FIELDS),
                       'returnGeometry': 'false', 'f': 'pjson'})
    return {
        'state': 'ID', 'issuer': 'Ada County', 'permit_id': number, 'record_kind': 'building_permit',
        'stage': 'closed' if closed else 'unknown', 'received_date': received.isoformat(),
        'closed_date': closure.isoformat() if closed else None,
        'source_disposition': disposition, 'source_status': f'{status} (APPStatus {app_code}, APPAprvlStatus {approval_code})',
        'source_url': f'{QUERY_URL}?{query}', 'inspection_status': 'unknown',
    }


class AdaCountyApplicationCollector:
    name = 'Ada County'
    landing_url = LAYER_URL
    progress_only = True

    def collect(self, *, today=None):
        today = today or datetime.now(MOUNTAIN).date()
        start = today - timedelta(days=WINDOW_DAYS - 1)
        start_utc = datetime.combine(start, time.min, MOUNTAIN).astimezone(timezone.utc)
        end_utc = datetime.combine(today + timedelta(days=1), time.min, MOUNTAIN).astimezone(timezone.utc)
        # The County view can expose the unassigned sentinel -1-BP.
        where = ("AppDivision = 'BL' AND APPFILE LIKE '%-BP' AND APPFILE <> '-1-BP' "
                 f"AND APPRcvdDate < TIMESTAMP '{end_utc:%Y-%m-%d %H:%M:%S}' "
                 f"AND (APPRcvdDate >= TIMESTAMP '{start_utc:%Y-%m-%d %H:%M:%S}' "
                 f"OR APPClosDate >= DATE '{start.isoformat()}')")

        layer = _get_json(LAYER_URL)
        fields = {field.get('name'): field.get('type') for field in layer.get('fields', []) if isinstance(field, dict)}
        if (layer.get('id') != 0 or layer.get('name') != 'Building Permits - All'
                or 'Query' not in str(layer.get('capabilities', '')).split(',')
                or layer.get('datesInUnknownTimezone') is not False or layer.get('dateFieldsTimeReference') is not None
                or any(fields.get(field) != kind for field, kind in FIELDS.items())):
            raise ValueError('Unexpected Ada County building application layer identity or schema')

        count = _get_json(QUERY_URL, where=where, returnCountOnly='true').get('count')
        if type(count) is not int or not 0 <= count <= MAX_RECORDS:
            raise ValueError('Ada County building application count is absent or exceeds the collection bound')

        enumeration = _get_json(QUERY_URL, where=where, returnIdsOnly='true')
        identifiers = enumeration.get('objectIds')
        if identifiers is None and 'objectIds' in enumeration and count == 0:
            identifiers = []  # ArcGIS reports an explicit empty ID result as null.
        if (enumeration.get('objectIdFieldName') != 'OBJECTID' or enumeration.get('exceededTransferLimit')
                or not isinstance(identifiers, list) or len(identifiers) != count
                or any(type(identifier) is not int or identifier <= 0 for identifier in identifiers)):
            raise ValueError('Ada County application count and object ID enumeration did not reconcile')

        # The County map view repeats some object IDs across matching map rows.
        # Require exact multiplicities before collapsing any application evidence.
        repeated = Counter(identifiers)
        unique_ids = sorted(repeated)
        progress = {}
        for offset in range(0, len(unique_ids), PAGE_SIZE):
            requested = unique_ids[offset:offset + PAGE_SIZE]
            expected = Counter({identifier: repeated[identifier] for identifier in requested})
            payload = _get_json(QUERY_URL, where=where, objectIds=','.join(map(str, expected)),
                                outFields=','.join(FIELDS), returnGeometry='false')
            features = payload.get('features')
            if (payload.get('exceededTransferLimit') or not isinstance(features, list)
                    or len(features) != sum(expected.values())):
                raise ValueError('Ada County application page was incomplete')
            seen = Counter()
            for feature in features:
                attributes = feature.get('attributes') if isinstance(feature, dict) else None
                oid = attributes.get('OBJECTID') if isinstance(attributes, dict) else None
                if type(oid) is not int or oid not in expected or seen[oid] >= expected[oid]:
                    raise ValueError('Ada County application page returned an unexpected object ID')
                seen[oid] += 1
                observation = _application(attributes, today, start)
                previous = progress.setdefault(observation['permit_id'], observation)
                if previous != observation:
                    raise ValueError('Ada County returned conflicting evidence for a building application ID')

        latest = max((row['received_date'] for row in progress.values()), default=None)
        note = (f'Official unincorporated Ada County building applications received or closed within a {WINDOW_DAYS}-day '
                f'window. Reconciled {count} map records into {len(progress)} application IDs. '
                'Receipt dates, source statuses and confirmed application closure only. '
                'The public layer has no issuance date or flag.')
        return CollectorResult(source=self.name, source_url=LAYER_URL, permits=[], note=note,
                               progress=list(progress.values()), progress_complete=True,
                               progress_source_name=SOURCE_NAME, progress_coverage_end=latest)
