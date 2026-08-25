from __future__ import annotations
from datetime import date
from .common import get, pdf_text

REPORTS_URL = 'https://www.cityofcaldwell.org/Departments/Community-Development/Building-Safety-Division/Building-Bulletins-Reports'
DIRECT_BASE = 'https://www.cityofcaldwell.org/files/assets/city/v/1/building/documents/permit-apps'
MONTH_NAMES = (
    'january','february','march','april','may','june',
    'july','august','september','october','november','december',
)


def _clean(value):
    return ' '.join((value or '').split())


def candidate_report_urls(as_of: date, months_back: int = 4):
    year = as_of.year
    month = as_of.month
    rows = []
    for _ in range(months_back):
        name = MONTH_NAMES[month - 1]
        rows.append({
            'year': year,
            'month': month,
            'label': f'{name.title()} {year}',
            'url': f'{DIRECT_BASE}/{name}-{year}-building-report.pdf',
        })
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return rows


class CaldwellReportDiscoveryCollector:
    name = 'Caldwell'
    landing_url = REPORTS_URL

    def collect(self):
        attempts = []
        selected = None
        selected_response = None
        for candidate in candidate_report_urls(date.today(), months_back=5):
            try:
                response = get(candidate['url'], timeout=90)
                content_type = (response.headers.get('content-type') or '').lower()
                is_pdf = response.content.startswith(b'%PDF') or 'pdf' in content_type
                attempts.append({
                    'label': candidate['label'],
                    'url': candidate['url'],
                    'status': response.status_code,
                    'content_type': content_type,
                    'is_pdf': is_pdf,
                })
                if is_pdf:
                    selected = candidate
                    selected_response = response
                    break
            except Exception as exc:
                attempts.append({
                    'label': candidate['label'],
                    'url': candidate['url'],
                    'error': f'{type(exc).__name__}: {exc}',
                })
        if not selected or selected_response is None:
            raise RuntimeError(f'No directly accessible Caldwell monthly PDF found; attempts={attempts}')
        text = pdf_text(selected_response.content)
        excerpt = _clean(text)[:9000]
        if not excerpt:
            raise RuntimeError(f"Caldwell direct PDF has no extractable text: {selected['url']}; attempts={attempts}")
        raise RuntimeError(
            f'Direct Caldwell report probe only; selected={selected}; attempts={attempts}; text_excerpt={excerpt}'
        )
