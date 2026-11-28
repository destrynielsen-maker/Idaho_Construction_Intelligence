"""Bounded collection from publisher-linked monthly building-permit reports."""

from calendar import month_name, monthrange
from datetime import date, datetime
from html.parser import HTMLParser
from io import BytesIO
import re
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .base import CollectorResult
from ..models import Permit


MONTHS = {name.casefold(): n for n, name in enumerate(month_name) if name}
MAX_REPORT_BYTES = 3_000_000
ACCESS_CHALLENGE = re.compile(rb'access denied|access restricted|captcha|challenge|'
                              rb'request blocked|verify you are human', re.I)


class _ReportLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.label = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.label = []

    def handle_data(self, data):
        if self.href:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.href:
            self.links.append((' '.join(' '.join(self.label).split()), self.href))
            self.href = None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get(url, limit=MAX_REPORT_BYTES):
    request = Request(quote(url, safe=':/?&=%'), headers={'User-Agent': 'IdahoConstructionIntelligence/1.0'})
    with build_opener(_NoRedirect()).open(request, timeout=25) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Publisher response exceeded the configured size limit')
        return data


def is_same_report_redirect(error, url):
    location = error.headers.get('Location')
    return bool(error.code == 302 and location and urljoin(url, location) == url
                and not error.headers.get('CF-Mitigated')
                and not ACCESS_CHALLENGE.search(error.read(4096)))


def month_from_label(label):
    match = re.fullmatch(r'([A-Za-z]+) (20\d{2})', label)
    if match and (month := MONTHS.get(match[1].casefold())):
        return date(int(match[2]), month, 1)
    return None


def report_date(value, period, today, fmt='%m/%d/%Y'):
    issued = datetime.strptime(value, fmt).date()
    if issued.replace(day=1) != period or issued > today:
        raise ValueError('Issue date falls outside the recognized report period')
    return issued


def valuation(value):
    if not value or value.strip() in {'-', '$-'}:
        return None
    amount = value.replace('$', '').replace(',', '').strip()
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', amount):
        raise ValueError('Unrecognized published dollar amount')
    return float(amount)


def pdf_layout(data, *, normalize_rotation=False):
    from pypdf import PdfReader

    if not data.startswith(b'%PDF-'):
        raise ValueError('Published report did not return a PDF')
    pdf = PdfReader(BytesIO(data))
    if not 1 <= len(pdf.pages) <= 25:
        raise ValueError('Published report page count is outside the supported range')
    for page in pdf.pages:
        if normalize_rotation and page.rotation:
            page.transfer_rotation_to_content()
        yield page.extract_text(extraction_mode='layout')


class MonthlyReportCollector:
    crawl_delay = 0
    scope = 'explicit new-building classes only'

    def report_month(self, label, url):
        raise NotImplementedError

    def report_url(self, url):
        return url

    def can_repeat_report_request(self, error, url):
        return False

    def parse_report(self, data, period, today, url):
        """Return permits and all distinct observed permit identities with issue dates."""
        raise NotImplementedError

    def make_permit(self, number, issued, kind, address, url, source_type, **fields):
        extra = fields.pop('raw', {})
        return Permit('ID', self.name, number, issued.isoformat(), kind, address, self.source_name, url,
                      county=self.county, status='Issued', stage='PERMITTED',
                      raw={'issue_date_verified': True, 'source_type': source_type, **extra}, **fields)

    def collect(self, today=None):
        today = today or date.today()
        started = monotonic()
        index = _get(self.landing_url, limit=1_200_000)
        parser = _ReportLinks()
        parser.feed(index.decode('utf-8-sig'))
        reports = {}
        for label, href in parser.links:
            url = urljoin(self.landing_url, href)
            period = self.report_month(label, url)
            if period is None or period > today:
                continue
            url = self.report_url(url)
            reports.setdefault(period, set()).add(url)
        if not reports:
            raise ValueError('No recognized monthly permit reports on publisher index')

        selected = sorted(reports, reverse=True)[:2]
        if any(len(reports[period]) != 1 for period in selected):
            raise ValueError('Conflicting publisher report links for one month')
        permits, observed = [], {}
        for period in selected:
            wait = self.crawl_delay - (monotonic() - started)
            if wait > 0:
                sleep(wait)
            started = monotonic()
            (url,) = reports[period]
            try:
                data = _get(url)
            except HTTPError as error:
                if not self.can_repeat_report_request(error, url):
                    raise
                error.close()
                wait = self.crawl_delay - (monotonic() - started)
                if wait > 0:
                    sleep(wait)
                started = monotonic()
                data = _get(url)
            result, identities = self.parse_report(data, period, today, url)
            if observed.keys() & identities.keys():
                raise ValueError('Duplicate permit identity across report periods')
            observed.update(identities)
            permits.extend(result)
        if not observed:
            raise ValueError('Publisher reports contain no verified issued permits')

        recent = selected[0]
        end = recent.replace(day=monthrange(recent.year, recent.month)[1])
        latest = max(observed.values())
        return CollectorResult(self.name, self.landing_url, permits,
            f'{len(observed)} issued permits checked across {len(selected)} monthly reports; '
            f'{len(permits)} accepted ({self.scope}); last issue {latest.isoformat()}.',
            status='stale' if (today - end).days > 60 else 'ok', latest_issued_date=latest.isoformat(),
            report_period_end=end.isoformat())
