"""County-issued building permits from Bannock County's monthly reports."""

import re
from urllib.parse import urlsplit

from .monthly_reports import MonthlyReportCollector, month_from_label, pdf_layout, report_date, valuation


HOST = 'www.bannockcounty.gov'
REPORT_LINK = re.compile(r'/wp-content/uploads/20\d{2}/\d{2}/([A-Za-z]+)-(20\d{2})-MONTHLY-BUILDING-PERMIT-REPORT\.pdf', re.I)
ISSUED_ROW = re.compile(r'\b([A-Z]{1,6}-\d{2}-\d+)\s{2,}(\d{1,2}/\d{1,2}/20\d{2})\b')


class BannockCountyPermitCollector(MonthlyReportCollector):
    name = 'Bannock County'
    county = 'Bannock'
    source_name = 'Bannock County monthly issued building permits'
    landing_url = f'https://{HOST}/planning/'
    scope = 'county-issued new single-family dwellings, separate from city permits'

    def report_month(self, label, url):
        period = month_from_label(label)
        target = urlsplit(url)
        match = REPORT_LINK.fullmatch(target.path)
        if target.scheme != 'https' or target.netloc != HOST or target.query or target.fragment or not match:
            return None
        return period if period == month_from_label(f'{match[1]} {match[2]}') else None

    def parse_report(self, data, period, today, url):
        return self.parse_pages(pdf_layout(data, normalize_rotation=True), period, today, url)

    def parse_pages(self, pages, period, today, url):
        permits, observed = [], {}
        header_verified = False
        for page in pages:
            for line in page.splitlines():
                if 'Record #' in line and 'Issued Date' in line and 'Project Description' in line:
                    header_verified = True
                match = ISSUED_ROW.search(line)
                if not match:
                    continue
                if not header_verified:
                    raise ValueError('Bannock issued-date table header is missing')
                number, when = match.groups()
                if len(number.split('-', 1)[0]) == 1:
                    continue  # This report includes separate municipality permit IDs such as Arimo's A- prefix.
                issued = report_date(when, period, today)
                if number in observed:
                    raise ValueError('Duplicate Bannock permit identity')
                observed[number] = issued
                if not number.startswith('RDP-'):
                    continue
                fields = re.split(r'\s{2,}', line[match.end():].strip())
                if len(fields) < 5 or fields[-3:-1] != ['New Dwelling', 'Single-Family']:
                    continue
                # The report supplies parcel and applicant information rather than a street address or contractor.
                permits.append(self.make_permit(number, issued, 'New Single Family Residential', '', url,
                    'Residential Dwelling Permit: New Dwelling / Single-Family', units=1, valuation=valuation(fields[-1])))
        if not header_verified:
            raise ValueError('Bannock issued-date table header is missing')
        return permits, observed
