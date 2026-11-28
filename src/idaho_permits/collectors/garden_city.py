"""Garden City's monthly CSV, limited to explicit new-building codes."""

import csv
from io import StringIO
import re
from urllib.parse import unquote, urlsplit

from .monthly_reports import MonthlyReportCollector, month_from_label, report_date, valuation


# Only the publisher codes checked against source records are eligible.
TYPES = {'CommNewConst': 'New commercial building', 'ResSFH': 'New single-family building'}
REQUIRED = {'Permit Type', 'Permit No.', 'Issue Date', 'Description', 'Address', 'Project Value'}
STATUS_FIELDS = {'Permit Status', 'Issue Status'}
NEW_HOUSE = re.compile(r'\bnew (?:sfh|single[- ]family)\b', re.I)
EXCLUDED = re.compile(r'\b(?:existing building|shell finish|tenant improvement|remodel|alteration|addition|demolition)\b', re.I)


class GardenCityPermitCollector(MonthlyReportCollector):
    name = 'Garden City'
    county = 'Ada'
    source_name = 'Garden City issued building permit CSV'
    landing_url = 'https://gardencityidaho.org/departments/development-services/activity-reports/'

    def report_month(self, label, url):
        asset = urlsplit(url)
        path = unquote(asset.path)
        match = re.fullmatch(r'/juniper-media-library/464/20\d{2}/\d{2}/(.+)\.csv', path)
        if (asset.scheme == 'https' and asset.netloc == 'storage.googleapis.com' and not asset.query
                and not asset.fragment and match and match[1] == label):
            return month_from_label(label)
        return None

    def parse_report(self, data, period, today, url):
        rows = csv.DictReader(StringIO(data.decode('utf-8-sig')))
        fields = set(rows.fieldnames or ())
        statuses = STATUS_FIELDS & fields
        if not REQUIRED.issubset(fields) or len(statuses) != 1:
            raise ValueError('Unrecognized Garden City monthly CSV header')
        status = statuses.pop()

        permits, observed = [], {}
        for row in rows:
            if None in row or any(row[key] is None for key in REQUIRED | {status}):
                raise ValueError('Invalid Garden City monthly CSV row width')
            if not any(row.values()) or row[status].strip().casefold() != 'issued':
                continue
            number = row['Permit No.'].strip()
            if not re.fullmatch(r'[A-Za-z0-9-]+', number) or number.upper() in observed:
                raise ValueError('Invalid or duplicate Garden City permit identity')
            issued = report_date(row['Issue Date'].strip(), period, today)
            observed[number.upper()] = issued
            source_type = row['Permit Type'].strip()
            description = ' '.join(row['Description'].split())
            address = ' '.join(row['Address'].split())
            if (source_type in TYPES and description and address and not EXCLUDED.search(description)
                    and (source_type != 'ResSFH' or NEW_HOUSE.search(description))):
                # The public CSV's contractor column can include private owner contact text.
                permits.append(self.make_permit(number, issued, TYPES[source_type], address, url,
                    source_type, valuation=valuation(row['Project Value']),
                    raw={'work_description': description}))
        return permits, observed
