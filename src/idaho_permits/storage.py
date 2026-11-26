import json
from pathlib import Path
from .models import Permit

def load_permits(path: Path):
    if not path.exists(): return {}
    data=json.loads(path.read_text(encoding='utf-8'))
    rows=data if isinstance(data,list) else data['permits']
    if not isinstance(rows,list):
        raise ValueError('Invalid historical permit ledger: expected a list')
    permits={}
    for row in rows:
        permit=Permit.from_dict(row)
        if permit.key in permits:
            raise ValueError('Duplicate historical permit identity; refusing to overwrite ledger')
        permits[permit.key]=permit
    return permits

def save_permits(path, permits, generated_at):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'generated_at':generated_at,'permits':[p.to_dict() for p in sorted(permits,key=lambda x:(x.issued_date,x.key),reverse=True)]},indent=2),encoding='utf-8')
