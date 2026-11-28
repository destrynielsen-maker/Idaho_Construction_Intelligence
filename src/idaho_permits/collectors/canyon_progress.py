"""Authoritative milestone evidence from Canyon County's ArcGIS tracker."""

from datetime import date, timedelta
from urllib.parse import urlencode


LAYER_URL = 'https://maps.canyonco.org/arcgisserver/rest/services/DSD/Building_Permits_NEW_2023/FeatureServer/1'
UNIX_DAY = date(1970, 1, 1)
MILLIS_PER_DAY = 86_400_000


def canyon_utc_civil(value, today):
    # County date fields are published as UTC-midnight civil dates.
    if type(value) is not int or value <= 0 or value % MILLIS_PER_DAY:
        return None
    days = value // MILLIS_PER_DAY
    if not (date(2000, 1, 1) - UNIX_DAY).days <= days <= (today - UNIX_DAY).days:
        return None
    return UNIX_DAY + timedelta(days=days)


def source_text(value):
    return (value.strip() or None) if isinstance(value, str) else None


def progress_from_tracker_attributes(attributes, today):
    number = source_text(attributes.get('BP_PermitNumber'))
    if not number:
        return None
    raw_received = attributes.get('BP_ReceivedDate')
    received = canyon_utc_civil(raw_received, today)
    review_date = canyon_utc_civil(attributes.get('BP_Building_Review_ResultDate'), today)
    issue_date = canyon_utc_civil(attributes.get('PermitIssuedDate'), today)
    closed_date = canyon_utc_civil(attributes.get('BP_DateClosed'), today)
    # Do not certify a milestone with a date recorded before receipt.
    if received:
        review_date = review_date if review_date and review_date >= received else None
        issue_date = issue_date if issue_date and issue_date >= received else None
        closed_date = closed_date if closed_date and closed_date >= received else None
    elif raw_received is not None:
        issue_date = None  # A malformed nonempty receipt cannot corroborate issue chronology.

    status = source_text(attributes.get('BP_Status'))
    approval = source_text(attributes.get('BP_Approval_Status'))
    review = source_text(attributes.get('BP_Building_Review_Result'))
    issue_flag = source_text(attributes.get('PemitIssued'))
    issued = issue_flag == 'Permit Issued'
    disposition = (status or '').casefold()
    if disposition == 'closed' or (disposition in {'expired', 'withdrawn', 'void'} and closed_date):
        stage = 'closed'
    elif disposition in {'expired', 'withdrawn', 'void'}:
        stage = 'unknown'
    elif issued or issue_date:
        stage = 'issued'
    elif (review or '').casefold() == 'approved':
        stage = 'review_approved_no_issue'
    elif (review or '').casefold() == 'in progress' or (disposition == 'active' and (approval or '').casefold() == 'in progress'):
        stage = 'application_under_review'
    else:
        stage = 'unknown'

    query = urlencode({'where': "BP_PermitNumber = '" + number.replace("'", "''") + "'",
                       'outFields': 'BP_PermitNumber,BP_Status,BP_Approval_Status,BP_ReceivedDate,'
                                    'BP_Building_Review_Result,BP_Building_Review_ResultDate,PemitIssued,'
                                    'PermitIssuedDate,BP_DateClosed',
                       'returnGeometry': 'false', 'f': 'pjson'})
    return {
        'state': 'ID', 'issuer': 'Canyon County', 'permit_id': number, 'record_kind': 'building_permit',
        'stage': stage, 'received_date': received.isoformat() if received else None,
        'review_result': review, 'review_date': review_date.isoformat() if review_date else None,
        'issued_flag': True if issued else None, 'issue_date': issue_date.isoformat() if issue_date else None,
        'closed_date': closed_date.isoformat() if closed_date else None,
        'source_disposition': disposition or None,
        'source_status': ' / '.join(filter(None, (status, approval))) or None,
        'source_url': f'{LAYER_URL}/query?{query}', 'inspection_status': 'unknown',
    }
