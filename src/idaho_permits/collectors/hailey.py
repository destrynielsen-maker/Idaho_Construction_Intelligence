"""Issued new-building records from Hailey's detailed monthly reports."""

import re
from urllib.parse import urlsplit

from .monthly_reports import MonthlyReportCollector, month_from_label, pdf_layout, report_date, valuation


TYPES = {
    'new single family': 'New single-family building',
    'new multi family': 'New multifamily building',
    'new multifamily': 'New multifamily building',
    'new commercial': 'New commercial building',
}
NUMBER = re.compile(r'\d{2}-\d{3,}')
DATE = re.compile(r'\d{2}-[A-Za-z]{3}-\d{2}')


class HaileyPermitCollector(MonthlyReportCollector):
    name = 'Hailey'
    county = 'Blaine'
    source_name = 'City of Hailey detailed issued building permit report'
    landing_url = 'https://haileycityhall.org/community-development/building-services/building-inspections-permit-reports/'

    def report_month(self, label, url):
        asset = urlsplit(url)
        month = re.fullmatch(r'([A-Za-z]+) Detailed', label)
        upload = re.fullmatch(r'/wp-content/uploads/(20\d{2})/(0[1-9]|1[0-2])/[^/]+\.pdf', asset.path, re.I)
        if (asset.scheme != 'https' or asset.netloc != 'haileycityhall.org' or asset.fragment or asset.query
                or not month or not upload):
            return None
        year, upload_month = map(int, upload.groups())
        period = month_from_label(f'{month[1]} {year}')
        if period and period.month > upload_month:
            period = period.replace(year=year - 1)
        return period

    def parse_report(self, data, period, today, url):
        permits, observed = [], {}
        for page_number, page in enumerate(pdf_layout(data), 1):
            lines = page.splitlines()
            if not any(all(field in line for field in ('Permit #', 'Permit Type', 'Date Issued', 'Physical Address'))
                       for line in lines):
                raise ValueError('Unrecognized Hailey detailed report header')
            for line in lines:
                columns = re.split(r' {2,}', line.strip())
                number = columns[0]
                if not NUMBER.fullmatch(number):
                    continue
                dates = [i for i, cell in enumerate(columns) if DATE.fullmatch(cell)]
                if len(dates) != 1 or dates[0] < 2 or len(columns) - dates[0] < 4 or number in observed:
                    raise ValueError('Unrecognized Hailey issued row or duplicate identity')
                i = dates[0]
                issued = report_date(columns[i], period, today, '%d-%b-%y')
                observed[number] = issued
                source_type = columns[i - 1]
                kind = TYPES.get(source_type.casefold().replace('-', ' '))
                if kind:
                    if not re.fullmatch(r'\d+', columns[-1]) or not columns[-2] or not columns[i + 1].startswith('$'):
                        raise ValueError('Hailey new-building row lacks address or valuation-column evidence')
                    permits.append(self.make_permit(number, issued, kind, columns[-2], f'{url}#page={page_number}',
                        source_type, valuation=valuation(columns[i + 1]), units=int(columns[-1]) or None))
        return permits, observed
