"""Detached dwellings from the City of Twin Falls' issued-permit archive."""

from calendar import monthrange
from datetime import datetime, timedelta
import re
from urllib.parse import urlsplit

from .issued_progress import issued_progress
from .monthly_reports import MonthlyReportCollector, month_from_label, pdf_layout, report_date, valuation


DATE = r'\d{1,2}/\d{1,2}/20\d{2}'
ENTRY = re.compile(r'^[ \t]*(?:Permit\s*#:|Total # of Permits:)[^\r\n]*', re.M)
# The real PDF layout can concatenate a value with the next field label.
HEADER = re.compile(rf'Permit\s*#:\s*(\d{{2}}-\d{{4,6}})\s+(.+?)\s*Application Date:\s*({DATE})\s*Issued Date:\s*({DATE})')
PERIOD = re.compile(rf'^[ \t]*({DATE}) to ({DATE})[ \t]*$', re.M)
SUBTOTAL = re.compile(r'Total # of Permits:\s*(\d+)')
SITE_VALUE = re.compile(r'^[ \t]*Permit Address:[ \t]*(.+?)[ \t]*Valuation:[ \t]*\$([\d,]+\.\d{2})[ \t]*Fees Paid:', re.M)
DESCRIPTION = re.compile(r'Description of Work:[ \t]*([^\r\n]+)')
CONTRACTOR = re.compile(r'Contractor:[ \t]*([^\r\n]*)')
DETACHED = 'Single-family Residential (detached)'
DWELLING = re.compile(r'^(?:new\s+)?single[ -]+(?:family[ -]+(?:dwelling|house|residence)|house)\b', re.I)
EXCLUDED = re.compile(r'\b(?:remodel|addition|repair|replace|alteration|mobile home|manufactured home|ADU|accessory|foundation only)\b', re.I)
NO_CONTRACTOR = {'owner/builder', 'owner-builder', 'tbd', 'unknown', 'none', 'n/a'}


def _source_date(value):
    return datetime.strptime(value, '%m/%d/%Y').date()


def _contractor(block, description_offset):
    match = CONTRACTOR.search(block, 0, description_offset)
    if not match:
        return None
    text = match[1]
    # The right column can continue below the printed Contractor label.
    column = match.start() - block.rfind('\n', 0, match.start()) - 1
    for line in block[match.end():description_offset].splitlines()[1:]:
        text += ' ' + line[column:]
    normalized = ' '.join(text.split())
    return normalized if normalized and normalized.casefold() not in NO_CONTRACTOR else None


class TwinFallsCityPermitCollector(MonthlyReportCollector):
    name = 'Twin Falls'
    county = 'Twin Falls'
    source_name = 'City of Twin Falls monthly issued building permit report'
    landing_url = 'https://www.tfid.org/Archive/48'
    scope = 'explicit detached single-family dwellings only'
    crawl_delay = 10

    def report_month(self, label, url):
        document = urlsplit(url)
        if (document.scheme != 'https' or document.netloc != 'www.tfid.org' or document.query
                or document.fragment or not re.fullmatch(r'/Archive/ViewFile/Item/\d+', document.path)):
            return None
        label = label.removeprefix('Most Recent Item ')
        if match := re.fullmatch(r'(20\d{2}) ([A-Za-z]+)', label):
            label = f'{match[2]} {match[1]}'
        return month_from_label(label)

    def collect(self, today=None):
        result = super().collect(today)
        result.progress = [issued_progress(permit) for permit in result.permits]
        result.progress_complete = True
        result.progress_source_name = 'Twin Falls monthly issued detached-dwelling reports'
        return result

    def parse_report(self, data, period, today, url):
        end = period + timedelta(days=monthrange(period.year, period.month)[1])
        pages = list(pdf_layout(data))
        permits, observed = [], {}
        category, remaining_count = None, 0
        for page_number, page in enumerate(pages, 1):
            bounds = PERIOD.findall(page)
            if (not re.search(r'^[ \t]*Permit List[ \t]*$', page, re.M)
                    or len(bounds) != 1 or tuple(map(_source_date, bounds[0])) != (period, end)
                    or not re.search(rf'^[ \t]*Page {page_number} of {len(pages)}[ \t]*$', page, re.M)):
                raise ValueError('Unexpected Twin Falls city report identity, period or page sequence')
            entries = list(ENTRY.finditer(page))
            for index, entry in enumerate(entries):
                label = entry[0].strip()
                if subtotal := SUBTOTAL.fullmatch(label):
                    if remaining_count == 0 or int(subtotal[1]) != remaining_count:
                        raise ValueError('Twin Falls city report section count does not reconcile')
                    category, remaining_count = None, 0
                    continue
                record = HEADER.fullmatch(label)
                if not record:
                    raise ValueError('Unrecognized Twin Falls city permit header')
                number, kind, applied_date, issued_date = record.groups()
                issued = report_date(issued_date, period, today)
                applied = _source_date(applied_date)
                if number in observed or applied > issued:
                    raise ValueError('Duplicate Twin Falls city permit or inconsistent application date')
                if category is not None and kind != category:
                    raise ValueError('Twin Falls city report section is missing its subtotal')
                category = kind
                remaining_count += 1
                observed[number] = issued
                if kind != DETACHED:
                    continue
                following = entries[index + 1].start() if index + 1 < len(entries) else len(page)
                block = page[entry.end():following]
                description_field = DESCRIPTION.search(block)
                if not description_field:
                    raise ValueError('Detached permit is missing its work description')
                description = ' '.join(description_field[1].split())
                if not DWELLING.search(description) or EXCLUDED.search(description):
                    continue
                site_value = SITE_VALUE.search(block)
                if not site_value:
                    raise ValueError('Detached permit is missing its site address or reported valuation')
                address = ' '.join(site_value[1].split())
                contractor = _contractor(block, description_field.start())
                raw = {'application_date': applied.isoformat(), 'work_description': description}
                if contractor:
                    raw['contractor_role'] = 'City-reported contractor'
                permits.append(self.make_permit(number, issued, 'New single-family building', address,
                    f'{url}#page={page_number}', kind, city=self.name, contractor=contractor,
                    valuation=valuation(site_value[2]), raw=raw))

        if remaining_count or not observed:
            raise ValueError('Twin Falls city report is incomplete or has no observed permits')
        return permits, observed
