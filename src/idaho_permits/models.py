from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass
class Permit:
    state: str
    jurisdiction: str
    permit_number: str
    issued_date: str
    permit_type: str
    address: str
    source_name: str
    source_url: str
    project_name: str | None = None
    building_use: str | None = None
    units: int | None = None
    valuation: float | None = None
    contractor: str | None = None
    owner: str | None = None
    developer: str | None = None
    architect: str | None = None
    apn: str | None = None
    area: str | None = None
    status: str | None = None
    subdivision: str | None = None
    county: str | None = None
    city: str | None = None
    stage: str = 'PERMITTED'
    classification: str = 'OTHER'
    new_construction_confidence: str = 'LOW'
    qualifies: bool = False
    score: int = 0
    sales_score: int = 0
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f'{self.state}:{self.jurisdiction}:{self.permit_number}'.upper()

    def to_dict(self):
        d=asdict(self); d['key']=self.key; return d

    @classmethod
    def from_dict(cls,data):
        clean=dict(data); clean.pop('key',None)
        return cls(**{k:v for k,v in clean.items() if k in cls.__dataclass_fields__})
