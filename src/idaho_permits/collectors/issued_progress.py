"""Progress projection for records whose collector has verified issuance."""

from ..models import Permit


def issued_progress(permit: Permit, *, received_date: str | None = None) -> dict:
    return {
        'state': permit.state,
        'issuer': permit.jurisdiction,
        'permit_id': permit.permit_number,
        'record_kind': 'building_permit',
        'stage': 'issued',
        'received_date': received_date,
        'issued_flag': True if permit.status == 'Issued' else None,
        'issue_date': permit.issued_date,
        'source_status': permit.status,
        'source_url': permit.source_url,
        'inspection_status': 'unknown',
    }
