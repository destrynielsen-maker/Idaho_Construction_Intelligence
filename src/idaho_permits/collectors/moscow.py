"""Moscow city-issued permits from the official monthly archive."""

from calendar import month_name
from datetime import date
import re
from urllib.parse import urlsplit

from .monthly_reports import MonthlyReportCollector, month_from_label, pdf_layout, report_date, valuation


HOST = 'www.ci.moscow.id.us'
PERMIT_ID = re.compile(r'BLD20\d{2}-\d+')
HEADER = ['Permit Number', 'Issue Date', 'Owner', 'Units', 'Contractor', 'Address', 'Permit Type', 'Total Valuation']
BUILDING_TYPES = {
    'NEW SINGLE FAMILY': 'New Single Family Residential',
    'NEW COMMERCIAL': 'New Commercial Building',
}


def archive_id(url):
    page = urlsplit(url)
    if page.scheme == 'https' and page.netloc == HOST and page.path == '/Archive.aspx' and not page.fragment:
        return re.fullmatch(r'ADID=(\d+)', page.query)
    return None


class MoscowPermitCollector(MonthlyReportCollector):
    name = 'Moscow'
    county = 'Latah'
    source_name = 'City of Moscow Monthly Building Permits Issued'
    landing_url = f'https://{HOST}/Archive.aspx?AMID=39'
    crawl_delay = 10
    scope = 'city-issued new single-family and commercial building permits'

    def report_month(self, label, url):
        match = re.fullmatch(r'(20\d{2}) ([A-Za-z]+) Building Permits Issued \(PDF\)', label)
        return month_from_label(f'{match[2]} {match[1]}') if match and archive_id(url) else None

    def report_url(self, url):
        # Moscow's linked Archive.aspx record redirects to this same-host PDF route.
        return f'https://{HOST}/ArchiveCenter/ViewFile/Item/{archive_id(url)[1]}'

    def parse_report(self, data, period, today, url):
        pages = pdf_layout(data, normalize_rotation=True)
        return self.parse_pages(pages, period, today, url)

    def parse_pages(self, pages, period, today, url):
        expected_period = f'{month_name[period.month]} {period.year}'.upper()
        permits, observed = [], {}
        for page in pages:
            rows = [re.split(r'\s{2,}', line.strip()) for line in page.splitlines() if line.strip()]
            if rows[:2] != [[expected_period], HEADER]:
                raise ValueError('Unrecognized Moscow report month or issue-date table')
            for columns in rows[2:]:
                number = columns[0]
                if not PERMIT_ID.fullmatch(number):
                    if number == 'OTHER BLDG PERMITS' or number.isdigit():
                        continue  # Aggregated or total rows have no individual permit IDs.
                    raise ValueError('Unrecognized Moscow issued-permit row')
                if len(columns) != len(HEADER) or number in observed:
                    raise ValueError('Incomplete or duplicate Moscow permit row')
                _, when, _, units, contractor, address, permit_type, amount = columns
                issued = report_date(when, period, today)
                observed[number] = issued
                kind = BUILDING_TYPES.get(permit_type)
                if kind is None:
                    continue
                if not units.isdigit() or not address:
                    raise ValueError('Moscow ground-up permit is missing numeric units or its address')
                company = contractor if re.search(r'\b(?:LLC|INC|CORP|CONSTRUCTION|BUILDERS|HOMES)\b', contractor, re.I) else None
                permits.append(self.make_permit(number, issued, kind, address, url, permit_type,
                    city=self.name, units=int(units), contractor=company, valuation=valuation(amount)))
        return permits, observed
