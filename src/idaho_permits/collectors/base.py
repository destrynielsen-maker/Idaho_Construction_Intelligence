from dataclasses import dataclass
from ..models import Permit
@dataclass
class CollectorResult:
    source: str
    source_url: str
    permits: list[Permit]
    note: str=''
    status: str='ok'
    latest_issued_date: str | None=None
    report_period_end: str | None=None
