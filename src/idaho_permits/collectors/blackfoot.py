"""Conservative detached-building intake from Blackfoot city-issued reports."""

import re
from urllib.parse import urljoin, urlsplit

from .monthly_reports import MonthlyReportCollector, month_from_label, pdf_layout, report_date


NUMBER = re.compile(r'(?:RES|COMM|MFG)-\d{2}-\d+')
DATE = re.compile(r'\d{1,2}/\d{1,2}/20\d{2}')
DETACHED = re.compile(r'\bstick[ -]built house\b|\bnew single[ -]family\b', re.I)
EXCLUDED = re.compile(r'\b(?:existing|addition|remodel\w*|alter\w*|replacement|relocat\w*|accessory|'
                      r'detached garage|twin[ -]home|duplex|manufactured|mobile home)\b', re.I)
ACCESS_CHALLENGE = re.compile(rb'access denied|access restricted|captcha|challenge|'
                              rb'request blocked|verify you are human', re.I)


class BlackfootPermitCollector(MonthlyReportCollector):
    name = 'Blackfoot'
    county = 'Bingham'
    source_name = 'City of Blackfoot issued building permit report'
    landing_url = 'https://www.cityofblackfoot.org/461/Monthly-Building-Permit-Reports'
    scope = 'explicit detached residential buildings only'
    crawl_delay = 10

    def report_month(self, label, url):
        asset = urlsplit(url)
        prefix = 'Building Permit Report '
        if (asset.scheme != 'https' or asset.netloc != 'www.cityofblackfoot.org' or asset.query or asset.fragment
                or not label.startswith(prefix)):
            return None
        expected = label.replace(' ', '-')
        if re.fullmatch(r'/DocumentCenter/View/\d+/' + re.escape(expected), asset.path, re.I):
            return month_from_label(label[len(prefix):])
        return None

    def can_repeat_report_request(self, error, url):
        # The city sometimes returns an ordinary 302 back to the same public report.
        location = error.headers.get('Location')
        return bool(error.code == 302 and location and urljoin(url, location) == url
                    and not error.headers.get('CF-Mitigated')
                    and not ACCESS_CHALLENGE.search(error.read(4096)))

    def parse_report(self, data, period, today, url):
        permits, observed = [], {}
        for page_number, page in enumerate(pdf_layout(data), 1):
            lines = page.splitlines()
            header = next((line for line in lines if all(token in line for token in
                           ('Record #', 'Record Type', 'Applicant Name', 'Address', 'Description'))), '')
            if not header or not any('Permit Issued' in line for line in lines[:5]):
                raise ValueError('Unrecognized Blackfoot permit issue/report headers')
            date_before_description = 'Permit Issued' in header
            description_start = header.index('Description') - 5
            continued = []
            for line in lines[lines.index(header) + 1:]:
                if not line.strip():
                    continue
                columns = re.split(r' {2,}', line.strip())
                number = columns[0]
                if not NUMBER.fullmatch(number):
                    if len(line) - len(line.lstrip()) >= description_start:
                        continued.append(line.strip())
                    else:
                        continued.clear()
                    continue
                dates = [i for i, cell in enumerate(columns) if DATE.fullmatch(cell)]
                if len(dates) != 1 or number in observed:
                    raise ValueError('Unrecognized Blackfoot issued row or duplicate identity')
                issue_column = dates[0]
                issued = report_date(columns[issue_column], period, today)
                observed[number] = issued
                if number.startswith('RES-') and len(columns) == 7 and columns[1] == 'Residential Building Permit':
                    if issue_column != (4 if date_before_description else 6):
                        raise ValueError('Blackfoot issue date is in an unexpected table column')
                    description = ' '.join([*continued, columns[5 if date_before_description else 4]])
                    size = columns[6 if date_before_description else 5].replace(',', '')
                    if DETACHED.search(description) and not EXCLUDED.search(description) and columns[3]:
                        permits.append(self.make_permit(number, issued, 'New single-family building', columns[3],
                            f'{url}#page={page_number}', columns[1], area=size if size.isdigit() else None,
                            raw={'work_description': description}))
                continued.clear()
        return permits, observed
