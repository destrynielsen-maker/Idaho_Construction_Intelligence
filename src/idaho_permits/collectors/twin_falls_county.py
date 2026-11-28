"""Twin Falls County issued-permit collector, pending hosted source verification."""

from decimal import Decimal
from io import BytesIO
import re
from urllib.parse import urlsplit

from .monthly_reports import MonthlyReportCollector, month_from_label, report_date


DATE = re.compile(r'\d{1,2}/\d{1,2}/20\d{2}')
NUMBER = re.compile(r'B\d{4}-\d{4,}')
STANDALONE_RESIDENCE = re.compile(r'\bnew single[ -]family\b', re.I)
COMMERCIAL_BUILDING = re.compile(r'\bbuildings?\b', re.I)
EXCLUDED_SCOPE = re.compile(r'\b(?:accessory|additions?|relocat\w*|move|remo(?:del|v)\w*|detached shop|existing)\b', re.I)
# Reuse the two normalized column layouts verified in the county intake preview.
NARROW = (62, 140, 210, 309, 398, 484, 511, 531, 613, 711, 793, 860, 949, 1058, 1098, 1160, 1248, 1307)
WIDE = (62, 149, 226, 319, 418, 495, 534, 593, 662, 758, 834, 900, 1036, 1135, 1183, 1240, 1298, 1355)
NORMALIZED_WIDTH = 1533


def _columns(words, width):
    markers = [w['x0'] * NORMALIZED_WIDTH / width for w in words if w['text'] == 'SUBTYPE']
    if len(markers) != 1:
        raise ValueError('Twin Falls County SUBTYPE header is missing or ambiguous')
    if 705 <= markers[0] <= 725:
        return NARROW
    if 750 <= markers[0] <= 770:
        return WIDE
    raise ValueError('Unsupported Twin Falls County report columns')


def _column(word, width, starts):
    x = word['x0'] * NORMALIZED_WIDTH / width
    return max((i for i, left in enumerate(starts) if x >= left), default=-1)


def _text(words):
    order = sorted(words, key=lambda w: (round(w['top'] / 2), w['x0']))
    return ' '.join(w['text'] for w in order)


def _money(value):
    value = re.sub(r'\s*,\s*', ',', value.strip().removeprefix('$').strip())
    if value in {'', '-'}:
        return None
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{2})?', value):
        raise ValueError('Unrecognized Twin Falls County valuation cell')
    return Decimal(value.replace(',', ''))


def _permit_type(subtype, work_type, description):
    if work_type != 'New' or EXCLUDED_SCOPE.search(description):
        return None
    if subtype == 'Single Family Residence' and STANDALONE_RESIDENCE.search(description):
        return 'New single-family building'
    if subtype == 'Commercial Building' and COMMERCIAL_BUILDING.search(description):
        return 'New commercial building'
    return None


class TwinFallsCountyPermitCollector(MonthlyReportCollector):
    name = 'Twin Falls County'
    county = 'Twin Falls'
    source_name = 'Twin Falls County monthly issued building permit report'
    landing_url = 'https://twinfallscounty.org/building_department/monthly_permits/'

    def report_month(self, label, url):
        asset = urlsplit(url)
        if (asset.scheme == 'https' and asset.netloc == 'twinfallscounty.org' and not asset.query
                and not asset.fragment and re.fullmatch(r'/wp-content/uploads/[^/]*issued[^/]*\.pdf', asset.path, re.I)):
            return month_from_label(label)
        return None

    def parse_report(self, data, period, today, url):
        # The existing geometry review dependency remains optional during preview.
        import pdfplumber

        if not data.startswith(b'%PDF-'):
            raise ValueError('Published Twin Falls County report did not return a PDF')
        permits, observed, printed_totals = [], {}, []
        computed_total = Decimal(0)
        starts = None
        with pdfplumber.open(BytesIO(data)) as pdf:
            if not 1 <= len(pdf.pages) <= 15:
                raise ValueError('Unsupported Twin Falls County report page count')
            for number, page in enumerate(pdf.pages, 1):
                if not 1.45 < page.width / page.height < 1.65:
                    raise ValueError('Unsupported Twin Falls County page layout')
                words = page.extract_words(x_tolerance=1.5, y_tolerance=2)
                if starts is None:
                    starts = _columns(words, page.width)
                positioned = [(_column(w, page.width, starts), w) for w in words]
                dates = sorted((w for i, w in positioned if i == 0 and DATE.fullmatch(w['text'])),
                               key=lambda w: w['bottom'])
                ids = [w for i, w in positioned if i == 1 and NUMBER.fullmatch(w['text'])]
                if not dates or len(dates) != len(ids):
                    raise ValueError('Unmatched issue-date and permit ID columns in Twin Falls County report')
                headers = [w for i, w in positioned if i == 0 and w['text'] == 'DAT_ISSUED'
                           and w['bottom'] < dates[0]['top']]
                if len(headers) > 1 or (number == 1 and not headers):
                    raise ValueError('Unverified Twin Falls County issue-date header')
                start = headers[0]['bottom'] + 0.1 if headers else 0.1
                for anchor in dates:
                    end = anchor['bottom'] + 1.5
                    cells = [[] for _ in starts]
                    for col, word in positioned:
                        if col >= 0 and start < word['bottom'] <= end:
                            cells[col].append(word)
                    issued = report_date(_text(cells[0]), period, today)
                    permit_id = _text(cells[1])
                    if not NUMBER.fullmatch(permit_id) or permit_id in observed:
                        raise ValueError('Invalid or duplicate Twin Falls County permit ID')
                    observed[permit_id] = issued
                    address, subtype, work_type, description = map(_text, cells[8:12])
                    amount = _money(_text(cells[12]))
                    computed_total += amount or Decimal(0)
                    if not (address and subtype and work_type and description):
                        raise ValueError('Required Twin Falls County row columns are missing')
                    if kind := _permit_type(subtype, work_type, description):
                        permits.append(self.make_permit(permit_id, issued, kind, address, f'{url}#page={number}',
                            subtype, valuation=float(amount) if amount is not None else None,
                            raw={'work_type': work_type, 'work_description': description}))
                    start = end
                remainder = [w for col, w in positioned if col == 12 and w['bottom'] > start]
                if remainder:
                    printed_totals.append(_money(_text(remainder)))
        if len(printed_totals) != 1 or printed_totals[0] != computed_total:
            raise ValueError('Twin Falls County report valuation total did not reconcile')
        return permits, observed
