"""Verified new buildings from the City of Jerome's monthly permit reports."""

from collections import Counter
from datetime import date
from io import BytesIO
import re
from urllib.parse import urlsplit

from .issued_progress import issued_progress
from .monthly_reports import MonthlyReportCollector, is_same_report_redirect, month_from_label, report_date, valuation


REPORT_TITLE = re.compile(r'([A-Za-z]+ 20\d{2}) (?:Permit Report|Issued Permits)', re.I)
REPORT_PATH = re.compile(r'/DocumentCenter/View/\d+/([A-Za-z0-9-]+)')
PERMIT_ID = re.compile(r'\b[A-Z]{2,6}-\d{2}-\d{5}\b')
FIELDS = (
    'permit number', 'municipal address', 'work type', 'category', 'work target', 'owner',
    'main sq ft', 'garage sq ft', 'total sq ft', 'issued date', 'estimated project value',
    'permit fees total',
)
NEW_NONRESIDENTIAL = {'commercial building': 'New commercial building', 'industrial building': 'New industrial building'}
NON_PRIMARY = re.compile(
    r'\b(?:foundation(?: work)? only|footings? only|tenant improvements?|build[ -]?out|'
    r'accessory structures?|additions?|remodels?|repairs?|demolition|site work)\b', re.I
)


def _project_type(work, category, target):
    if work.casefold() != 'new':
        return None
    category, target = category.casefold(), target.casefold()
    if category == 'residential building' and target == 'single-family dwelling':
        return 'New single-family building'
    if target not in {'', '-', 'n/a', 'other', 'foundation', 'footing'} and not NON_PRIMARY.search(target):
        return NEW_NONRESIDENTIAL.get(category)
    return None


class JeromePermitCollector(MonthlyReportCollector):
    name = 'Jerome'
    county = 'Jerome'
    source_name = 'City of Jerome monthly issued building permit report'
    landing_url = 'https://ci.jerome.id.us/353/Permit-Reports'
    scope = 'explicit new single-family, commercial and industrial buildings only'
    crawl_delay = 10

    def report_month(self, label, url):
        asset = urlsplit(url)
        path = REPORT_PATH.fullmatch(asset.path)
        title = REPORT_TITLE.fullmatch(label)
        if (asset.scheme == 'https' and asset.netloc == 'ci.jerome.id.us' and not asset.query
                and not asset.fragment and path and title and path[1].replace('-', ' ').casefold() == label.casefold()):
            return month_from_label(title[1])
        return None

    def can_repeat_report_request(self, error, url):
        return is_same_report_redirect(error, url)

    def collect(self, today=None):
        today = today or date.today()
        result = super().collect(today)
        result.progress = [issued_progress(permit) for permit in result.permits]
        result.progress_complete = True
        result.progress_source_name = self.source_name
        result.progress_coverage_end = (result.latest_issued_date if result.report_period_end > today.isoformat()
                                        else result.report_period_end)
        return result

    def parse_report(self, data, period, today, url):
        import pdfplumber

        if not data.startswith(b'%PDF-'):
            raise ValueError('Jerome report did not return a PDF')
        permits, observed, seen = [], {}, set()
        with pdfplumber.open(BytesIO(data)) as pdf:
            if not 1 <= len(pdf.pages) <= 25:
                raise ValueError('Jerome report page count is outside the supported range')
            for page_number, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                if len(tables) != 1 or not tables[0]:
                    raise ValueError('Jerome report did not contain an identifiable permit table')
                header, *rows = tables[0]
                columns = tuple(' '.join((cell or '').split()).rstrip(':').casefold() for cell in header)
                if columns != FIELDS:
                    raise ValueError('Unrecognized Jerome issued-permit columns')
                if not rows or any(len(row) != len(FIELDS) for row in rows):
                    raise ValueError('Jerome permit rows do not match the recognized columns')
                page_ids = PERMIT_ID.findall(page.extract_text() or '')
                if Counter(page_ids) != Counter((row[0] or '').strip() for row in rows):
                    raise ValueError('Jerome report table identities do not reconcile with its text')
                for row in rows:
                    number, address, work, category, target, _, _, _, _, issued_date, value, _ = (
                        ' '.join((cell or '').split()) for cell in row
                    )
                    if not PERMIT_ID.fullmatch(number) or number in seen:
                        raise ValueError('Invalid or duplicate Jerome permit identity')
                    seen.add(number)
                    date_fmt = '%m/%d/%y' if len(issued_date.rsplit('/', 1)[-1]) == 2 else '%m/%d/%Y'
                    issued = report_date(issued_date, period, today, fmt=date_fmt)
                    if not number.startswith('BLD-'):
                        continue
                    observed[number] = issued
                    kind = _project_type(work, category, target)
                    if not kind:
                        continue
                    if not address:
                        raise ValueError('Jerome new building permit lacks a municipal address')
                    permits.append(self.make_permit(number, issued, kind, address, f'{url}#page={page_number}',
                        category, city=self.name, building_use=category, project_name=target,
                        valuation=valuation(value.replace('$', '').strip()),
                        raw={'work_type': work, 'work_target': target}))
        return permits, observed
