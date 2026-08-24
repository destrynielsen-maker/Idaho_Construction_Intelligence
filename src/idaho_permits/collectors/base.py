from dataclasses import dataclass
from ..models import Permit
@dataclass
class CollectorResult:
    source: str
    source_url: str
    permits: list[Permit]
    note: str=''
