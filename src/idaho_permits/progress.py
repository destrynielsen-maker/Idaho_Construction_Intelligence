"""Persist source-observed permit progress independently of the lead ledger."""

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit


DATE_FIELDS = ('received_date', 'review_date', 'issue_date', 'closed_date')
TEXT_FIELDS = ('review_result', 'source_status', 'inspection_status')
TRACKED_FIELDS = ('stage', 'received_date', 'review_result', 'review_date', 'issued_flag',
                  'issue_date', 'closed_date', 'source_status', 'inspection_status')
BUILDING_STAGES = {'application_under_review', 'review_approved_no_issue', 'issued', 'closed', 'unknown'}
TERMINAL_DISPOSITIONS = {'closed', 'expired', 'withdrawn', 'void'}
STAGE_DATE_FIELD = {'review_approved_no_issue': 'review_date', 'issued': 'issue_date', 'closed': 'closed_date'}


def _text(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 240
            or any(ord(char) < 32 for char in value)):
        raise ValueError('Invalid text in permit progress evidence')
    return value.strip()


def _iso_date(value, latest=None):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ValueError('Permit progress date must be an ISO civil date')
    civil = date.fromisoformat(value)
    if latest is not None and civil > latest:
        raise ValueError('Permit progress date is later than observation')
    return value


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Invalid permit progress observation timestamp')
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('Permit progress observation must have a timezone')
    return stamp.astimezone(timezone.utc)


def _source_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 32 for char in value):
        raise ValueError('Invalid public permit progress source URL')
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError('Permit progress evidence requires a public HTTPS source URL')
    return value


def _identity(state, issuer):
    if not isinstance(state, str) or not re.fullmatch(r'[A-Z]{2}', state):
        raise ValueError('Invalid permit progress issuer state')
    issuer = _text(issuer)
    if ':' in issuer:
        raise ValueError('Invalid permit progress issuer identity')
    return state, issuer


def _permit(row, today):
    if not isinstance(row, dict):
        raise ValueError('Expected a permit progress record')
    state, issuer = _identity(row.get('state'), row.get('issuer'))
    number = _text(row.get('permit_id'))
    kind, stage = _text(row.get('record_kind')), _text(row.get('stage'))
    if not (kind == 'planning' and stage == 'planning' or kind == 'building_permit' and stage in BUILDING_STAGES):
        raise ValueError('Unrecognized permit progress kind or stage')
    result = {'key': f'{state}:{issuer}:{number}'.upper(), 'state': state, 'issuer': issuer,
              'permit_id': number, 'record_kind': kind, 'stage': stage}
    for field in DATE_FIELDS:
        result[field] = _iso_date(row.get(field), today)
    for field in TEXT_FIELDS:
        value = row.get(field)
        result[field] = _text(value) if value is not None else None
    flag = row.get('issued_flag')
    if flag is not None and type(flag) is not bool:
        raise ValueError('Permit progress issue flag must be true, false, or null')
    result['issued_flag'] = flag
    result['source_url'] = _source_url(row.get('source_url'))
    status_url = row.get('source_status_url') or result['source_url']
    result['source_status_url'] = _source_url(status_url) if result['source_status'] is not None else None
    disposition = row.get('source_disposition')
    result['source_disposition'] = _text(disposition) if disposition is not None else None
    return result


def _event_date(field, row):
    if field in DATE_FIELDS:
        return row[field]
    if field == 'review_result':
        return row['review_date']
    if field == 'issued_flag' and row[field] is True:
        return row['issue_date']
    if field == 'stage':
        return row.get(STAGE_DATE_FIELD.get(row['stage']))
    return None


def _refresh_row(old, row, now):
    if old is None:
        return {**row, 'last_observed_at': now, 'changes': []}
    if old['record_kind'] != row['record_kind']:
        raise ValueError('Permit progress identity changed between a planning record and a building permit')
    if _timestamp(now) < _timestamp(old['last_observed_at']):
        return old

    stored = {**old, 'last_observed_at': now, 'source_url': row['source_url'], 'source_name': row['source_name']}
    for field in TRACKED_FIELDS:
        if row[field] is not None and not (field == 'inspection_status' and row[field] == 'unknown'):
            stored[field] = row[field]
    if stored['review_result'] != old['review_result']:
        stored['review_date'] = row['review_date']
    if row['source_status'] is not None:
        stored['source_status_url'] = row['source_status_url']
    disposition = row['source_disposition']
    if disposition is not None:
        stored['source_disposition'] = disposition
    reopened = (disposition == 'active' and old['source_disposition'] in TERMINAL_DISPOSITIONS
                and row['source_name'] == old['source_name'])
    # Upstream rolling views can hide earlier verified evidence. Preserve the
    # attained stage unless the source reports a different current disposition.
    if reopened and (stored['issued_flag'] is True or stored['issue_date']):
        stored['stage'] = 'issued'
    elif reopened or disposition in TERMINAL_DISPOSITIONS:
        stored['stage'] = row['stage']
    elif (row['stage'] == 'unknown' or old['stage'] == 'closed'
          or (old['stage'] == 'issued' and row['stage'] not in {'issued', 'closed'})):
        stored['stage'] = old['stage']
    changes = [dict(field=field, previous_value=old[field], new_value=stored[field], observed_at=now,
                    event_date=None if reopened and field == 'stage' else _event_date(field, row))
               for field in TRACKED_FIELDS if old[field] != stored[field]]
    stored['changes'] = old['changes'] + changes
    return stored


class PermitProgress:
    def __init__(self):
        self.permits = {}
        self.sources = {}

    @classmethod
    def load(cls, path):
        ledger = cls()
        if not path.exists():
            return ledger
        data = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or not isinstance(data.get('permits'), list)
                or not isinstance(data.get('sources'), list)):
            raise ValueError('Invalid permit progress ledger')
        for record in data['permits']:
            if not isinstance(record, dict):
                raise ValueError('Invalid permit progress ledger record')
            stamp = _timestamp(record.get('last_observed_at'))
            row = _permit(record, stamp.date())
            key = row['key']
            if key != record.get('key') or key in ledger.permits or not isinstance(record.get('changes'), list):
                raise ValueError('Invalid or duplicate permit progress ledger identity')
            name = record.get('source_name')
            ledger.permits[key] = {**row, 'last_observed_at': stamp.isoformat(), 'changes': record['changes'],
                                   'source_name': _text(name) if name is not None else None}
        for record in data['sources']:
            if not isinstance(record, dict):
                raise ValueError('Invalid permit progress ledger source')
            state, issuer = _identity(record.get('state'), record.get('issuer'))
            name = _text(record.get('source_name'))
            key = state, issuer.upper(), name
            success = record.get('last_successful_refresh')
            if key in ledger.sources:
                raise ValueError('Duplicate permit progress ledger source')
            ledger.sources[key] = dict(state=state, issuer=issuer, source_name=name,
                source_url=_source_url(record.get('source_url')),
                last_successful_refresh=_timestamp(success).isoformat() if success is not None else None,
                latest_date_covered=_iso_date(record.get('latest_date_covered')))
        sources_by_issuer = {}
        for state, issuer, source_name in ledger.sources:
            sources_by_issuer.setdefault((state, issuer), []).append(source_name)
        for row in ledger.permits.values():
            names = sources_by_issuer.get((row['state'], row['issuer'].upper()), [])
            if row['source_name'] is None and len(names) == 1:
                row['source_name'] = names[0]
        return ledger

    def observe(self, source_name, source_url, rows, observed_at, *, complete=False, coverage_end=None,
                default_issuer=None):
        if not isinstance(rows, list) or type(complete) is not bool:
            raise ValueError('Invalid permit progress batch')
        source_name, source_url = _text(source_name), _source_url(source_url)
        stamp = _timestamp(observed_at)
        now = stamp.isoformat()
        end = _iso_date(coverage_end, stamp.date()) if complete else None
        observed = {}
        groups = {}
        for record in rows:
            row = _permit(record, stamp.date())
            row['source_name'] = source_name
            key = row['key']
            if key in observed and observed[key] != row:
                raise ValueError('Conflicting permit progress rows in one source batch')
            observed[key] = row
            source_key = row['state'], row['issuer'].upper(), source_name
            groups.setdefault(source_key, []).append(row)
        if complete and not rows and default_issuer is not None:
            state, issuer = _identity(*default_issuer)
            groups[(state, issuer.upper(), source_name)] = []

        pending_permits = {key: _refresh_row(self.permits.get(key), row, now) for key, row in observed.items()}
        pending_sources = {}
        for key, group in groups.items():
            old = self.sources.get(key, {})
            issuer = old.get('issuer') or (group[0]['issuer'] if group else default_issuer[1])
            dates = [row[field] for row in group for field in DATE_FIELDS if row[field] is not None] if complete else []
            if end is not None:
                dates.append(end)
            newest = max(dates, default=None)
            previous_end = old.get('latest_date_covered')
            coverage_url = source_url
            if previous_end is not None and (newest is None or newest < previous_end):
                newest, coverage_url = previous_end, old['source_url']
            last_success = old.get('last_successful_refresh')
            if complete and (last_success is None or stamp >= _timestamp(last_success)):
                last_success = now
            pending_sources[key] = dict(state=key[0], issuer=issuer, source_name=source_name, source_url=coverage_url,
                last_successful_refresh=last_success, latest_date_covered=newest)

        self.permits.update(pending_permits)
        self.sources.update(pending_sources)

    def save(self, canonical, public):
        payload = {'sources': [self.sources[key] for key in sorted(self.sources)],
                   'permits': [self.permits[key] for key in sorted(self.permits)]}
        data = (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
        if self.permits or self.sources or canonical.exists():
            _replace(canonical, data)
        _replace(public, data)


def _replace(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        destination = Path(temporary.name)
    try:
        destination.write_bytes(data)
        destination.replace(path)
    finally:
        destination.unlink(missing_ok=True)
