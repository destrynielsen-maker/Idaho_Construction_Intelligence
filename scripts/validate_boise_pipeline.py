from collections import Counter
from datetime import date, timedelta
from pathlib import Path
import json

sources_path = Path('public/data/sources.json')
permits_path = Path('public/data/permits.json')

sources_payload = json.loads(sources_path.read_text(encoding='utf-8'))
sources = sources_payload.get('collector_status', sources_payload.get('sources', []))
print('SOURCE_STATUS')
for row in sources:
    print(row.get('source'), row.get('status'), row.get('records_seen'), row.get('qualifying_records'), row.get('note', ''))

names = {row.get('source') for row in sources}
expected = {
    'Boise', 'Boise Issued Building Permits', 'Eagle', 'Canyon County',
    'Caldwell', "Coeur d'Alene", 'Kootenai County', 'Meridian', 'Nampa'
}
missing = expected - names
if missing:
    raise SystemExit(f'missing collectors: {sorted(missing)}')

boise_source = next(row for row in sources if row.get('source') == 'Boise Issued Building Permits')
if boise_source.get('status') != 'ok':
    raise SystemExit(f'Boise issued source unhealthy: {boise_source}')
if (boise_source.get('records_seen') or 0) <= 0 or (boise_source.get('qualifying_records') or 0) <= 0:
    raise SystemExit(f'Boise issued source returned no useful records: {boise_source}')

permits_payload = json.loads(permits_path.read_text(encoding='utf-8'))
permits = permits_payload.get('permits', [])
boise_permits = [p for p in permits if p.get('jurisdiction') == 'Boise' and p.get('stage') == 'PERMITTED']
numbers = {p.get('permit_number') for p in boise_permits}
print('BOISE_PERMITTED_COUNT', len(boise_permits))
print('BOISE_CLASSIFICATIONS', dict(Counter(p.get('classification') for p in boise_permits)))
print('BOISE_NUMBERS', sorted(numbers))

if 'BLD26-01423' not in numbers:
    raise SystemExit('known true Boise commercial new-building control is missing')
for bad in ('BLD26-01687', 'BLD26-00239'):
    if bad in numbers:
        raise SystemExit(f'known Boise false positive escaped final guards: {bad}')

cutoff = date.today() - timedelta(days=45)
for permit in boise_permits:
    issued = date.fromisoformat(permit['issued_date'])
    if issued < cutoff or issued > date.today():
        raise SystemExit(f'Boise permit outside issue-date window: {permit["permit_number"]}')
    if permit.get('status') != 'Issued':
        raise SystemExit(f'non-issued Boise permit escaped: {permit["permit_number"]}')
    if not permit.get('qualifies'):
        raise SystemExit(f'nonqualifying Boise permit escaped: {permit["permit_number"]}')

required = [
    'public/data/permits.json',
    'public/data/sources.json',
    'public/data/builders.json',
    'public/feeds/new-construction.xml',
    'public/feeds/single-family.xml',
    'public/feeds/multifamily.xml',
    'public/feeds/commercial.xml',
]
for item in required:
    if not Path(item).exists():
        raise SystemExit(f'missing generated artifact: {item}')

print('BOISE_PIPELINE_VALIDATION_OK')
