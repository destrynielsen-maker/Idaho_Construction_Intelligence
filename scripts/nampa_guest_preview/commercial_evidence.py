"""Review manually collected Nampa commercial evidence without changing feeds."""

import argparse
import hashlib
import json
import re
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit


CASE_HOST = 'nampaid-energovpub.tylerhost.net'
REPORT_HOST = 'www.cityofnampa.us'
PERMIT_TYPE = 'Commercial New Complete Building With Tenant'
ISSUED_STATUSES = {'Issued', 'Finaled', 'Finalized'}
PERMIT_ID = re.compile(r'COM-\d+-20\d{2}')
REPORT_PATH = re.compile(r'/DocumentCenter/View/\d+/Commercial-Permit---Plan-Review-Status---[A-Za-z]+')
REPORT_ROW = re.compile(r'^\s*(COM-\d+-20\d{2})\s+\d{1,2}/\d{1,2}/20\d{2}\b')
NEW_BUILDING = re.compile(
    r'\bnew (?:commercial )?building\b|'
    r'\b(?:construct|build) (?:a|an) (?:[\w-]+ ){0,6}building\b', re.I
)
EXCLUDED_SCOPE = re.compile(
    r'\b(?:existing building|pool amenit\w*|carports?|pergolas?|tenant improvements?|remodel\w*|'
    r'alterations?|repairs?|additions?|roofs?|reroofs?|occupancy only|demolition|solar|racking)\b', re.I
)


def official_report_url(value):
    url = urlsplit(value)
    return (url.scheme == 'https' and url.netloc == REPORT_HOST and REPORT_PATH.fullmatch(url.path)
            and not url.query and not url.fragment)


def scope_from_layout(layout, wanted_ids):
    """Read only the Scope of Work column under a verified Nampa report header."""
    lines = layout.splitlines()
    starts = [(i, match.group(1)) for i, line in enumerate(lines) if (match := REPORT_ROW.match(line))]
    if not any(permit_id in wanted_ids for _, permit_id in starts):
        return []
    header = next((line for line in lines[:starts[0][0]] if 'Scope of Work' in line), '')
    right_header = re.search(r'\s{2,}(?=Stated\b|Valuation\b|Issue Date\b|Fire\b)',
                             header.partition('Scope of Work')[2])
    if ('City of Nampa' not in layout or 'Commercial Permit - Plan Review Status' not in layout
            or not header or not right_header):
        raise ValueError('Unrecognized Nampa report scope column')
    left = header.index('Scope of Work')
    right = left + len('Scope of Work') + right_header.end()
    ends = [position for position, _ in starts[1:]] + [len(lines)]
    matches = []
    for (start, permit_id), end in zip(starts, ends):
        if permit_id not in wanted_ids:
            continue
        body = [line[left:right].strip() for line in lines[start:end]
                if not re.match(r'^\s*Page\s+\d+\s+of\b', line, re.I)]
        scope = ' '.join(part for part in body if part)
        if scope:
            matches.append((permit_id, scope))
    return matches


def read_scope_report(path, report_url, wanted_ids):
    from pypdf import PdfReader

    if not official_report_url(report_url) or path.stat().st_size > 12_000_000:
        raise ValueError('Invalid City scope report URL or file size')
    data = path.read_bytes()
    if not data.startswith(b'%PDF-'):
        raise ValueError('Scope evidence file is not a PDF')
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted or len(reader.pages) > 30:
        raise ValueError('Encrypted or oversized scope report')
    digest = hashlib.sha256(data).hexdigest()
    rows = []
    for page, pdf_page in enumerate(reader.pages, start=1):
        layout = pdf_page.extract_text(extraction_mode='layout')
        rows.extend({'permit_id': permit_id, 'report_url': report_url, 'page': page, 'scope': scope,
                     'report_sha256': digest} for permit_id, scope in scope_from_layout(layout, wanted_ids))
    return rows


def review(cases, scope_rows, start, end):
    if end < start or (end - start).days > 6:
        raise ValueError('Select a single municipal week or a shorter window')

    scopes = {}
    for evidence in scope_rows:
        permit_id = evidence['permit_id']
        if (PERMIT_ID.fullmatch(permit_id) is None or permit_id in scopes or not official_report_url(evidence['report_url'])
                or type(evidence['page']) is not int or evidence['page'] < 1
                or ('report_sha256' in evidence and not re.fullmatch(r'[a-f0-9]{64}', evidence['report_sha256']))
                or not evidence['scope'].strip()):
            raise ValueError(f'Invalid or duplicate City scope evidence for {permit_id}')
        scopes[permit_id] = evidence

    seen = set()
    results = []
    for case in cases:
        permit_id = case['permit_id']
        case_url = urlsplit(case['case_url'])
        issue_date = date.fromisoformat(case['issue_date'])
        cents = case['valuation_cents']
        if (not PERMIT_ID.fullmatch(permit_id) or permit_id in seen
                or case_url.scheme != 'https' or case_url.netloc != CASE_HOST or case_url.query
                or not re.fullmatch(r'/Apps/SelfService(?:/NampaIDProd)?/?', case_url.path, re.I)
                or not re.fullmatch(r'/permit/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', case_url.fragment, re.I)
                or case['permit_type'] != PERMIT_TYPE or case['status'] not in ISSUED_STATUSES
                or case['issue_date'] != issue_date.isoformat() or not start <= issue_date <= end
                or (cents is not None and (type(cents) is not int or cents < 0))):
            raise ValueError(f'Invalid or duplicate public case evidence for {permit_id}')
        seen.add(permit_id)

        evidence = scopes.get(permit_id)
        disposition = 'needs_scope_evidence'
        if evidence:
            scope = ' '.join(evidence['scope'].split())
            if EXCLUDED_SCOPE.search(scope):
                disposition = 'excluded_scope'
            elif NEW_BUILDING.search(scope):
                disposition = 'new_building_candidate'

        results.append({
            'permit_id': permit_id,
            'permit_type': PERMIT_TYPE,
            'issue_date': issue_date.isoformat(),
            'status': case['status'],
            'valuation_cents': cents,
            'case_url': case['case_url'],
            'decision': disposition,
            'scope_evidence': {key: evidence[key] for key in ('report_url', 'page', 'scope', 'report_sha256')
                               if key in evidence} if evidence else None,
        })
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case_bundle', type=Path)
    parser.add_argument('--scope-pdf', action='append', nargs=2, metavar=('LOCAL_PDF', 'OFFICIAL_URL'), default=[],
                        help='Apply a City Plan Review Status PDF already obtained through an authorized route.')
    args = parser.parse_args()
    payload = json.loads(args.case_bundle.read_text(encoding='utf-8'))
    cases = payload['cases']
    reports = [*payload.get('scope_evidence', [])]
    for path, url in args.scope_pdf:
        reports.extend(read_scope_report(Path(path), url, {r['permit_id'] for r in cases}))
    reviewed = review(cases, reports,
                      date.fromisoformat(payload['start']), date.fromisoformat(payload['end']))
    print(json.dumps(reviewed, indent=2))
