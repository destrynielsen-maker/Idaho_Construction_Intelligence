"""New primary building permits from the City of Hayden's issued reports."""

from calendar import month_name
from datetime import date
import re
from urllib.parse import urlsplit

from .issued_progress import issued_progress
from .monthly_reports import MonthlyReportCollector, pdf_layout, report_date, valuation


REPORT_PATH = re.compile(
    r'/Docs/Government/Departments/Building/Reports/PermitsIssued(0[1-9]|1[0-2])-(20\d{2})\.pdf', re.I
)
REPORT_LABEL = re.compile(r'Permits Issued (0[1-9]|1[0-2]) (20\d{2})', re.I)
FIELDS = ('Permit Number', 'Issued Date', 'Contractor', 'Address', 'Value', 'Amount Paid', 'Work Description')
RECORD = re.compile(r'^(?P<number>[A-Z]{2,3}\d{2}-\d{3,})\s+(?P<date>\d{1,2}/\d{1,2}/20\d{2})(?=\s|$)')
CATEGORY = re.compile(r"[A-Za-z][A-Za-z &'./()\-]+")
ADDRESS = re.compile(r'(?<!\S)\d+\s+(?=\w)')
OVERLAPPING_ADDRESS = re.compile(r'(?<=[A-Za-z])\d+\s+(?=[NSEW]\s)')
MONEY = r'\$\s?(?:[0-9,]+\.\d{2}|-)'
ENDING = re.compile(rf'(?P<value>{MONEY})\s{{2,}}{MONEY}\s+(?P<description>\S.*)$')
TYPES = {
    'Com New Construction': 'New commercial building',
    'Res Single Family': 'New single-family building',
    'Res Townhome': 'New townhome',
}
NON_PRIMARY = re.compile(
    r'\b(?:foundation work final approved|foundation(?: work)? only|rv cover|patio cover|'
    r'pre[- ]built shed|tenant improvement only|addition to existing|remodel)\b', re.I
)
FUTURE_TENANT_WORK = re.compile(r'\bto be built out under\s+separate tenant improvements?\b.*', re.I)


class HaydenPermitCollector(MonthlyReportCollector):
    name = 'Hayden'
    county = 'Kootenai'
    source_name = 'City of Hayden issued building permit report'
    landing_url = 'https://www.haydenid.gov/departments/building/index.php'
    scope = 'explicit new commercial buildings, single-family dwellings and townhomes only'

    def report_month(self, label, url):
        asset = urlsplit(url)
        # The City index declares a site-root HTML base for relative Docs links.
        path = asset.path.removeprefix('/departments/building')
        document, title = REPORT_PATH.fullmatch(path), REPORT_LABEL.fullmatch(label)
        if (asset.scheme == 'https' and asset.netloc == 'www.haydenid.gov' and not asset.fragment
                and (not asset.query or re.fullmatch(r't=\d{14,17}', asset.query))
                and document and title and document.groups() == title.groups()):
            return date(int(title[2]), int(title[1]), 1)
        return None

    def report_url(self, url):
        asset = urlsplit(url)
        path = asset.path.removeprefix('/departments/building')
        # The City redirects these exact public documents to its Revize tenant.
        query = f'?{asset.query}' if asset.query else ''
        return f'https://cms2.revize.com/revize/haydenid{path}{query}'

    def collect(self, today=None):
        result = super().collect(today)
        result.progress = [issued_progress(permit) for permit in result.permits]
        result.progress_complete = True
        result.progress_source_name = 'Hayden monthly issued new-building reports'
        return result

    def parse_report(self, data, period, today, url):
        permits, observed = [], {}
        category = None
        title = f'{month_name[period.month]} {period.year} Permits Issued'
        for page_number, page in enumerate(pdf_layout(data), 1):
            lines = [line.rstrip() for line in page.splitlines() if line.strip()]
            if page_number == 1 and (not lines or lines.pop(0).strip() != title):
                raise ValueError('Hayden issue-report title does not match the discovered month')
            if lines and lines[0].strip() == title:
                lines.pop(0)
            header = re.split(r' {2,}', lines[0].strip()) if lines else []
            if tuple(header) != FIELDS:
                raise ValueError('Unrecognized Hayden issued-permit column layout')
            address_column = lines[0].index('Address')
            description_column = lines[0].index('Work Description')
            for line in lines[1:]:
                record = RECORD.match(line)
                if not record:
                    if line == line.strip() and len(line) < address_column and CATEGORY.fullmatch(line):
                        category = line
                        continue
                    raise ValueError('Unrecognized Hayden issued-permit line')
                number = record['number']
                if category is None or number in observed:
                    raise ValueError('Hayden record lacks a work category or has a duplicate identity')
                issued = report_date(record['date'], period, today)
                observed[number] = issued
                kind = TYPES.get(category)
                if kind and number.startswith('PB'):
                    ending = ENDING.search(line, address_column)
                    if not ending or abs(ending.start('description') - description_column) > 2:
                        raise ValueError('Hayden new-building line has misplaced valuation or work description')
                    description = ' '.join(ending['description'].split())
                    if NON_PRIMARY.search(description):
                        continue
                    address_matches = [match for match in ADDRESS.finditer(line, record.end(), ending.start())
                                       if abs(match.start() - address_column) <= 2]
                    if not address_matches:
                        # A wide contractor cell can touch the directional street address in the PDF text.
                        address_matches = [match for match in OVERLAPPING_ADDRESS.finditer(line, record.end(), ending.start())
                                           if 0 <= match.start() - address_column <= 8]
                    if len(address_matches) != 1:
                        raise ValueError('Hayden new-building line has an ambiguous site address')
                    site = address_matches[0].start()
                    contractor = ' '.join(line[record.end():site].split()) or None
                    address = ' '.join(line[site:ending.start()].split())
                    project = FUTURE_TENANT_WORK.sub('', description).strip()
                    raw = {'work_description': description}
                    if contractor:
                        raw['contractor_role'] = 'City-reported contractor'
                    permits.append(self.make_permit(number, issued, kind, address, f'{url}#page={page_number}',
                        category, city=self.name, project_name=project, contractor=contractor,
                        valuation=valuation(ending['value']), raw=raw))
        return permits, observed
