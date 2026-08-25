from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .base import CollectorResult
from ..models import Permit

LAYER_URL = 'https://services1.arcgis.com/WHM6qC35aMtyAAlN/ArcGIS/rest/services/Development_Tracker_Open_Data/FeatureServer/0'
QUERY_URL = LAYER_URL + '/query'
PAGE_SIZE = 2000

BOISE_BUILDING_SEARCH_URL = 'https://permits.cityofboise.org/CitizenAccess/Cap/CapHome.aspx?module=Building'


def _date(value):
    if value in (None, ''):
        return ''
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    text = str(value).strip()
    if len(text) >= 10 and text[4] == '-' and text[7] == '-':
        return text[:10]
    return text


def permit_from_feature(feature: dict) -> Permit | None:
    a = feature.get('attributes') or {}
    record_id = str(a.get('RecordID') or '').strip()
    if not record_id:
        return None
    record_type = str(a.get('RecordType') or 'Planning').strip()
    description = str(a.get('Description') or '').strip()
    record_name = str(a.get('RecordName') or '').strip()
    website = str(a.get('Website') or '').strip() or LAYER_URL
    return Permit(
        state='ID',
        jurisdiction='Boise',
        permit_number=record_id,
        issued_date=_date(a.get('AddToTrackerDate')),
        permit_type=f'Planning - {record_type}',
        address=str(a.get('PropertyAddress') or '').strip(),
        source_name='Boise Development Tracker',
        source_url=website,
        project_name=record_name or None,
        building_use=description or None,
        area=str(a.get('ComprehensivePlanningArea') or '').strip() or None,
        status=str(a.get('Status') or '').strip() or None,
        city='Boise',
        county='Ada',
        stage='PLANNING',
        raw=a,
    )


class BoiseDevelopmentCollector:
    name = 'Boise'
    landing_url = LAYER_URL

    def collect(self):
        permits = []
        offset = 0
        while True:
            params = {
                'where': '1=1',
                'outFields': '*',
                'returnGeometry': 'false',
                'f': 'json',
                'resultOffset': offset,
                'resultRecordCount': PAGE_SIZE,
                'orderByFields': 'AddToTrackerDate DESC',
            }
            response = requests.get(QUERY_URL, params=params, timeout=45)
            response.raise_for_status()
            payload = response.json()
            if payload.get('error'):
                raise RuntimeError(f"ArcGIS error: {payload['error']}")
            features = payload.get('features') or []
            for feature in features:
                permit = permit_from_feature(feature)
                if permit:
                    permits.append(permit)
            if len(features) < PAGE_SIZE:
                break
            offset += len(features)
        return CollectorResult(
            'Boise',
            LAYER_URL,
            permits,
            'Official City of Boise Development Tracker active planning projects; daily early-lead source',
        )


class BoiseIssuedPermitCollector:
    """Official issued new-construction building permits from Boise Accela Citizen Access."""

    name = 'Boise Issued Building Permits'
    landing_url = BOISE_BUILDING_SEARCH_URL
    source_url = BOISE_BUILDING_SEARCH_URL
    lookback_days = 45
    residential_discovery_days = 240
    commercial_discovery_days = 365
    max_pages = 75

    type_field = 'ctl00$PlaceHolderMain$generalSearchForm$ddlGSPermitType'
    status_field = 'ctl00$PlaceHolderMain$generalSearchForm$ddlGSCapStatus'
    start_field = 'ctl00$PlaceHolderMain$generalSearchForm$txtGSStartDate'
    end_field = 'ctl00$PlaceHolderMain$generalSearchForm$txtGSEndDate'
    start_state_field = 'ctl00$PlaceHolderMain$generalSearchForm$txtGSStartDate_ext_ClientState'
    end_state_field = 'ctl00$PlaceHolderMain$generalSearchForm$txtGSEndDate_ext_ClientState'
    search_target = 'ctl00$PlaceHolderMain$btnNewSearch'

    type_specs = (
        ('residential', 'Building/Building/402-404-New Res/NA', {402, 403, 404}),
        ('commercial', 'Building/Building/502-New or Added Commercial/NA', {502}),
        ('multifamily', 'Building/Building/506-New Multi-Family/NA', {506}),
    )

    permit_number_re = re.compile(r'^BLD\d{2}-\d{5}$', re.I)
    adu_re = re.compile(r'\bADU\b|accessory\s+dwelling', re.I)
    excluded_structure_re = re.compile(
        r'foundation\s+only|footing(?:s)?(?:\s*/\s*|\s+and\s+)?foundation|no\s+vertical\s+construction|'
        r'\bcarport\b|covered\s+parking|parking\s+structure|shade\s+structure|\bcanopy\b|temporary\s+structure',
        re.I,
    )
    alteration_re = re.compile(r'\bremodel\b|\balteration\b|tenant\s+improvement|\baddition\b|\badditions\b', re.I)
    new_building_re = re.compile(
        r'(?:\bnew\b.{0,110}\b(?:building|warehouse|hotel|office|retail|restaurant|industrial|facility|store|school|church|shop)\b|'
        r'\bconstruction\s+of\b.{0,80}\bnew\b.{0,100}\b(?:building|warehouse|hotel|office|facility)\b|'
        r'\bground[- ]up\b)',
        re.I,
    )
    multifamily_re = re.compile(r'\bmultifamily\b|multi-family|\bapartment\b|\bfourplex\b|\btriplex\b|\bduplex\b|\btownhome\b|\btownhouse\b', re.I)

    def collect(self, session: requests.Session | None = None) -> CollectorResult:
        session = session or requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; IdahoConstructionIntelligence/0.1; public-permit-research)'
        })
        today = self._today()
        issue_cutoff = today - timedelta(days=self.lookback_days)
        permits: dict[str, Permit] = {}
        successful_types = 0

        for family, type_value, codes in self.type_specs:
            discovery_days = self.residential_discovery_days if family == 'residential' else self.commercial_discovery_days
            start = today - timedelta(days=discovery_days)
            rows = self._search_type(session, type_value, start, today)
            successful_types += 1
            for row in rows:
                if not self._row_scope_candidate(family, row):
                    continue
                detail = self._detail(session, row['source_url'])
                permit = self._permit(row, detail, family, codes, issue_cutoff, today)
                if permit:
                    permits[permit.key] = permit

        if successful_types != len(self.type_specs):
            raise RuntimeError('Boise Accela did not complete all issued-building type queries')

        return CollectorResult(
            self.name,
            self.source_url,
            list(permits.values()),
            'Official City of Boise Accela Citizen Access issued Building records; anonymous type/status search with authoritative detail-page issue dates and a rolling 45-day issue-date cutoff',
        )

    def _search_type(self, session: requests.Session, type_value: str, start: date, end: date) -> list[dict]:
        response = session.get(self.search_url, timeout=90)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        self._guard_page(soup, 'initial search')

        # Accela only populates valid statuses after the record type is selected.
        payload = self._successful_controls(soup)
        payload[self.type_field] = type_value
        payload['__EVENTTARGET'] = self.type_field
        payload['__EVENTARGUMENT'] = ''
        typed = session.post(
            self.search_url,
            data=payload,
            headers={'Referer': self.search_url, 'Origin': 'https://permits.cityofboise.org'},
            timeout=120,
        )
        typed.raise_for_status()
        soup = BeautifulSoup(typed.text, 'html.parser')
        self._guard_page(soup, 'record-type postback')
        status_select = soup.find('select', {'name': self.status_field})
        statuses = {
            ' '.join(option.stripped_strings).strip(): option.get('value', '')
            for option in status_select.find_all('option')
        } if status_select else {}
        if statuses.get('Issued') != 'Issued':
            raise RuntimeError('Boise Accela Issued status option is unavailable for target building type')

        payload = self._successful_controls(soup)
        payload.update({
            self.type_field: type_value,
            self.status_field: 'Issued',
            self.start_field: self._form_date(start),
            self.end_field: self._form_date(end),
            self.start_state_field: '',
            self.end_state_field: '',
            '__EVENTTARGET': self.search_target,
            '__EVENTARGUMENT': '',
        })
        posted = session.post(
            self.search_url,
            data=payload,
            headers={'Referer': self.search_url, 'Origin': 'https://permits.cityofboise.org'},
            timeout=150,
        )
        posted.raise_for_status()
        soup = BeautifulSoup(posted.text, 'html.parser')
        self._guard_page(soup, 'issued search results')

        table = soup.find('table', id='ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList')
        plain = ' '.join(soup.stripped_strings)
        if not table:
            if re.search(r'(?:no records|no results|0 record)', plain, re.I):
                return []
            raise RuntimeError('Boise Accela issued search response did not contain a result grid')

        rows: list[dict] = []
        for page_number in range(self.max_pages):
            rows.extend(self._parse_result_rows(soup))
            next_link = next(
                (a for a in soup.find_all('a', href=True) if ' '.join(a.stripped_strings).strip() == 'Next >'),
                None,
            )
            if not next_link:
                break
            if page_number == self.max_pages - 1:
                raise RuntimeError('Boise Accela issued search exceeded pagination safety cap')
            match = re.search(r"__doPostBack\('([^']*)','([^']*)'\)", next_link.get('href', ''))
            if not match:
                raise RuntimeError('Boise Accela pagination schema changed')
            page_payload = self._successful_controls(soup)
            page_payload['__EVENTTARGET'] = match.group(1)
            page_payload['__EVENTARGUMENT'] = match.group(2)
            page_response = session.post(
                self.search_url,
                data=page_payload,
                headers={'Referer': self.search_url, 'Origin': 'https://permits.cityofboise.org'},
                timeout=150,
            )
            page_response.raise_for_status()
            soup = BeautifulSoup(page_response.text, 'html.parser')
            self._guard_page(soup, 'paginated issued search results')

        # The server-side status filter is authoritative; fail closed if it leaks.
        if any((row.get('status') or '').strip().lower() != 'issued' for row in rows):
            raise RuntimeError('Boise Accela Issued status filter leaked a non-issued building record')
        return rows

    @classmethod
    def _parse_result_rows(cls, soup: BeautifulSoup) -> list[dict]:
        table = soup.find('table', id='ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList')
        if not table:
            return []
        rows: list[dict] = []
        for tr in table.find_all('tr'):
            link = tr.find('a', id=re.compile(r'_hlPermitNumber$'))
            if not link:
                continue

            def value(suffix: str, fallback_index: int | None = None) -> str:
                node = tr.find(id=re.compile(re.escape(suffix) + r'$'))
                if node:
                    return ' '.join(node.stripped_strings).strip()
                cells = tr.find_all('td')
                if fallback_index is not None and len(cells) > fallback_index:
                    return ' '.join(cells[fallback_index].stripped_strings).strip()
                return ''

            number = ' '.join(link.stripped_strings).strip()
            if not cls.permit_number_re.match(number):
                continue
            source_url = urljoin(cls.search_url, link.get('href', ''))
            cls._guard_url(source_url)
            rows.append({
                'application_date': cls._date_text(value('_lblUpdatedTime', 1)),
                'permit_number': number,
                'status': value('_lblStatus', 3),
                'description': value('_lblDescription', 4),
                'project_name': value('_lblProjectName', 5),
                'address': value('_lblPermitAddress', 6),
                'source_url': source_url,
            })
        return rows

    def _detail(self, session: requests.Session, source_url: str) -> dict:
        self._guard_url(source_url)
        response = session.get(source_url, headers={'Referer': self.search_url}, timeout=90)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        self._guard_page(soup, 'permit detail')
        status_node = soup.find(id='ctl00_PlaceHolderMain_lblRecordStatus')
        status = ' '.join(status_node.stripped_strings).strip() if status_node else ''
        text = ' '.join(soup.stripped_strings)
        issued = self._date_text(self._capture(text, r'Issued Date:\s*(\d{1,2}/\d{1,2}/\d{4})'))
        received = self._date_text(self._capture(text, r'Received Date:\s*(\d{1,2}/\d{1,2}/\d{4})'))
        application_code = self._positive_int(self._capture(text, r'Application Type:\s*(\d{3})\b'))
        type_of_permit = self._capture(text, r'Type of Permit:\s*(.+?)(?=\s+Type of Use:)')
        type_of_use = self._capture(text, r'Type of Use:\s*(.+?)(?=\s+Type of Work:)')
        type_of_work = self._capture(text, r'Type of Work:\s*(.+?)(?=\s+(?:Building Height|Total Building Area|Additional Features|Dwelling Units))')
        detached_adu = self._capture(text, r'This residence is a detached Accessory Dwelling Unit \(ADU\):\s*(Yes|No)')
        units = self._positive_int(self._capture(text, r'Number of Units in this building:\s*(\d+)'))
        existing_area = self._number(self._capture(text, r'Existing Building Area:\s*([\d,.]+)'))
        new_area = self._number(self._capture(text, r'New Building Area:\s*([\d,.]+)'))
        total_area = self._number(self._capture(text, r'Total Building Area:\s*([\d,.]+)'))
        valuation = self._money(self._capture(text, r'Total Project Value:\s*\$?([\d,]+(?:\.\d+)?)'))
        if valuation is None:
            valuation = self._money(self._capture(text, r'Initial Value:\s*\$?([\d,]+(?:\.\d+)?)'))
        contractor = self._licensed_professional(soup)
        return {
            'status': status,
            'issued_date': issued,
            'received_date': received,
            'application_code': application_code,
            'type_of_permit': type_of_permit,
            'type_of_use': type_of_use,
            'type_of_work': type_of_work,
            'detached_adu': detached_adu,
            'units': units,
            'existing_building_area': existing_area,
            'new_building_area': new_area,
            'total_building_area': total_area,
            'valuation': valuation,
            'contractor': contractor,
        }

    def _permit(
        self,
        row: dict,
        detail: dict,
        family: str,
        allowed_codes: set[int],
        cutoff: date,
        today: date,
    ) -> Permit | None:
        if not self._row_scope_candidate(family, row):
            return None
        if (row.get('status') or '').strip().lower() != 'issued':
            return None
        if (detail.get('status') or '').strip().lower() != 'issued':
            return None
        if detail.get('application_code') not in allowed_codes:
            raise RuntimeError('Boise Accela record-type filter leaked an unexpected building application type')
        issued = detail.get('issued_date') or ''
        if not issued:
            return None
        issued_date = date.fromisoformat(issued)
        if issued_date < cutoff or issued_date > today:
            return None
        if not self._detail_scope_is_new(family, row, detail):
            return None

        scope = self._scope_text(row, detail)
        if family == 'residential':
            if re.search(r'\btown(?:home|house)\b|\bduplex\b', scope, re.I):
                permit_type = 'New Townhome Residential'
                building_use = 'New townhome / attached residential dwelling'
            else:
                permit_type = 'New Single Family Residential'
                building_use = detail.get('type_of_use') or 'Single Family Dwelling'
            units = 1
        elif family == 'multifamily':
            permit_type = 'New Multifamily Building'
            building_use = detail.get('type_of_use') or 'Multifamily residential building'
            units = detail.get('units')
        else:
            permit_type = 'New Commercial Building'
            building_use = detail.get('type_of_use') or 'Commercial building'
            units = detail.get('units')

        return Permit(
            state='ID',
            jurisdiction='Boise',
            permit_number=row['permit_number'],
            issued_date=issued,
            permit_type=permit_type,
            address=row.get('address') or '',
            source_name='City of Boise Accela Citizen Access',
            source_url=row['source_url'],
            project_name=row.get('project_name') or None,
            building_use=building_use,
            units=units,
            valuation=detail.get('valuation'),
            contractor=detail.get('contractor'),
            status='Issued',
            city='Boise',
            county='Ada',
            stage='PERMITTED',
            raw={
                'description': row.get('description'),
                'application_date': row.get('application_date'),
                'received_date': detail.get('received_date'),
                'application_code': detail.get('application_code'),
                'type_of_permit': detail.get('type_of_permit'),
                'type_of_use': detail.get('type_of_use'),
                'type_of_work': detail.get('type_of_work'),
                'detached_adu': detail.get('detached_adu'),
                'existing_building_area': detail.get('existing_building_area'),
                'new_building_area': detail.get('new_building_area'),
                'total_building_area': detail.get('total_building_area'),
                'source_issue_date_authoritative': True,
                'source_new_construction_authoritative': True,
            },
        )

    @classmethod
    def _row_scope_candidate(cls, family: str, row: dict) -> bool:
        text = cls._norm(' '.join(filter(None, [row.get('description'), row.get('project_name')])))
        if not text:
            return family == 'residential'
        if family == 'residential':
            return not cls.adu_re.search(text)
        if cls.excluded_structure_re.search(text):
            return False
        if family == 'multifamily':
            return bool(cls.multifamily_re.search(text)) and bool(re.search(r'\bnew\b|construction', text, re.I))
        if cls.new_building_re.search(text):
            return True
        if cls.alteration_re.search(text):
            return False
        return bool(re.search(r'\bconstruct(?:ion)?\b.{0,100}\b(?:building|warehouse|hotel|office|facility|store|school|church|shop)\b', text, re.I))

    @classmethod
    def _detail_scope_is_new(cls, family: str, row: dict, detail: dict) -> bool:
        text = cls._scope_text(row, detail)
        if family == 'residential':
            if (detail.get('detached_adu') or '').strip().lower() == 'yes' or cls.adu_re.search(text):
                return False
            permit_kind = cls._norm(detail.get('type_of_permit'))
            work_kind = cls._norm(detail.get('type_of_work'))
            use = cls._norm(detail.get('type_of_use'))
            structured_new = permit_kind == 'new structure' and work_kind.startswith('new')
            dwelling = any(x in use or x in text for x in ('single family', 'townhome', 'townhouse', 'duplex', 'dwelling', 'residence'))
            return structured_new and dwelling

        if cls.excluded_structure_re.search(text):
            return False
        if family == 'multifamily':
            units = detail.get('units') or 0
            return units >= 2 and bool(cls.multifamily_re.search(text)) and bool(re.search(r'\bnew\b|construction', text, re.I))

        # Boise's 502 category mixes new buildings and additions. A positive new-building
        # phrase is required; addition/remodel language alone is not sufficient.
        if cls.new_building_re.search(text):
            return True
        if cls.alteration_re.search(text):
            return False
        return bool(re.search(r'\bconstruct(?:ion)?\b.{0,100}\b(?:building|warehouse|hotel|office|facility|store|school|church|shop)\b', text, re.I))

    @classmethod
    def _scope_text(cls, row: dict, detail: dict) -> str:
        return cls._norm(' '.join(filter(None, [
            row.get('description'), row.get('project_name'), detail.get('type_of_permit'),
            detail.get('type_of_use'), detail.get('type_of_work'),
        ])))

    @staticmethod
    def _norm(value) -> str:
        return re.sub(r'\s+', ' ', str(value or '')).strip().lower()

    @classmethod
    def _successful_controls(cls, soup: BeautifulSoup) -> dict[str, str]:
        form = soup.find('form', id='aspnetForm')
        if not form:
            raise RuntimeError('Boise Accela aspnetForm not found')
        payload: dict[str, str] = {}
        for element in form.find_all('input'):
            name = element.get('name')
            kind = (element.get('type') or 'text').lower()
            if not name or kind in {'submit', 'button', 'image', 'file'}:
                continue
            if kind in {'checkbox', 'radio'} and not element.has_attr('checked'):
                continue
            payload[name] = element.get('value', '')
        for element in form.find_all('textarea'):
            if element.get('name'):
                payload[element['name']] = element.get_text()
        for element in form.find_all('select'):
            name = element.get('name')
            if not name:
                continue
            chosen = element.find('option', selected=True) or element.find('option')
            payload[name] = chosen.get('value', '') if chosen else ''
        return payload

    @classmethod
    def _guard_page(cls, soup: BeautifulSoup, context: str) -> None:
        if not soup.find('form', id='aspnetForm'):
            raise RuntimeError(f'Boise Accela {context} did not contain the expected ASP.NET form')
        plain = ' '.join(soup.stripped_strings)
        if re.search(r'application error|server error|temporarily unavailable', plain, re.I):
            raise RuntimeError(f'Boise Accela {context} returned an error page')

    @classmethod
    def _guard_url(cls, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'permits.cityofboise.org':
            raise RuntimeError('Boise Accela returned an unexpected permit-detail URL')

    @staticmethod
    def _capture(text: str, pattern: str) -> str | None:
        match = re.search(pattern, text, re.I)
        return match.group(1).strip() if match else None

    @staticmethod
    def _licensed_professional(soup: BeautifulSoup) -> str | None:
        table = soup.find(id='ctl00_PlaceHolderMain_licenseeGeneralInfoView_tbl_licensedps')
        if not table:
            table = soup.find(id=re.compile(r'tbl_licensedps$', re.I))
        if not table:
            return None
        values = [' '.join(x.split()).strip() for x in table.stripped_strings]
        values = [x for x in values if x and x.lower() != 'licensed professional']
        return values[0] if values else None

    @staticmethod
    def _number(value) -> float | None:
        if value in (None, ''):
            return None
        try:
            return float(str(value).replace(',', '').strip())
        except ValueError:
            return None

    @classmethod
    def _money(cls, value) -> float | None:
        return cls._number(value)

    @staticmethod
    def _positive_int(value) -> int | None:
        try:
            number = int(float(str(value).replace(',', '').strip()))
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _date_text(value) -> str:
        text = str(value or '').strip()
        if not text:
            return ''
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
            return text
        match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
        if not match:
            return ''
        try:
            return date(int(match.group(3)), int(match.group(1)), int(match.group(2))).isoformat()
        except ValueError:
            return ''

    @staticmethod
    def _form_date(value: date) -> str:
        return value.strftime('%m/%d/%Y')

    @staticmethod
    def _today() -> date:
        return date.today()
