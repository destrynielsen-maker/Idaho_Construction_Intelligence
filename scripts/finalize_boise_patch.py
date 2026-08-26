from pathlib import Path

source = Path('src/idaho_permits/collectors/boise.py')
text = source.read_text()

old_work = "type_of_work = self._capture(text, r'Type of Work:\\s*(.+?)(?=\\s+(?:Building Height|Total Building Area|Additional Features|Dwelling Units))')"
new_work = "type_of_work = self._capture(text, r'Type of Work:\\s*(.+?)(?=\\s+(?:Type of Construction|Building Height|Existing Building Area|New Building Area|Total Building Area|Additional Features|Dwelling Units))')"
if old_work not in text:
    raise SystemExit('expected Boise Type of Work parser pattern not found')
text = text.replace(old_work, new_work, 1)

old_commercial = """        # Boise's 502 category mixes new buildings and additions. A positive new-building
        # phrase is required; addition/remodel language alone is not sufficient.
        if cls.new_building_re.search(text):
            return True
        if cls.alteration_re.search(text):
            return False
        return bool(re.search(r'\\bconstruct(?:ion)?\\b.{0,100}\\b(?:building|warehouse|hotel|office|facility|store|school|church|shop)\\b', text, re.I))"""
new_commercial = """        # Boise's 502 category mixes ground-up buildings, additions and alterations.
        # Prefer Boise's structured Type of Work and building-area fields over descriptive
        # text so words like \"new foundations\" cannot turn an addition into a new-building lead.
        work_kind = cls._norm(detail.get('type_of_work'))
        if work_kind:
            if not work_kind.startswith('new'):
                return False
            new_area = detail.get('new_building_area')
            if new_area is not None and new_area <= 0:
                return False
            return not cls.excluded_structure_re.search(text)
        if cls.excluded_structure_re.search(text) or cls.alteration_re.search(text):
            return False
        return bool(
            cls.new_building_re.search(text)
            or re.search(r'\\bconstruct(?:ion)?\\b.{0,100}\\b(?:building|warehouse|hotel|office|facility|store|school|church|shop)\\b', text, re.I)
        )"""
if old_commercial not in text:
    raise SystemExit('expected Boise commercial scope block not found')
text = text.replace(old_commercial, new_commercial, 1)
text = text.replace('.strip().lower().lower()', '.strip().lower()')
source.write_text(text)

tests = Path('tests/test_boise_collector.py')
test_text = tests.read_text()
old_ground = """        detail = self.detail(
            application_code=502,
            type_of_permit=None,
            type_of_use='Industrial',
            type_of_work=None,
            new_building_area=27512.0,
            total_building_area=27512.0,
            valuation=4200000.0,
        )"""
new_ground = """        detail = self.detail(
            application_code=502,
            type_of_permit='New Structure',
            type_of_use='Industrial',
            type_of_work='New',
            existing_building_area=0.0,
            new_building_area=27512.0,
            total_building_area=27512.0,
            valuation=4200000.0,
        )"""
if old_ground not in test_text:
    raise SystemExit('expected commercial ground-up test fixture not found')
test_text = test_text.replace(old_ground, new_ground, 1)

marker = '    def test_foundation_only_commercial_is_rejected(self):\n'
addition = """    def test_commercial_structured_alteration_and_addition_are_rejected(self):
        screen_wall = self.row(
            'Permit to construct a new exterior architectural screen wall on the existing FAB building. '
            'Any alterations to the fire system require a separate permit.',
            project='MICRON FAB Architectural Screen Wall',
        )
        screen_detail = self.detail(
            application_code=502,
            type_of_permit='Other',
            type_of_use='Industrial',
            type_of_work='Alteration',
            existing_building_area=8190.0,
            new_building_area=None,
            total_building_area=8190.0,
        )
        dental_addition = self.row(
            'Addition and remodel with construction of new foundations and new exterior bearing walls.',
            project='Building Addition for Idaho Street Dental',
            number='BLD26-00239',
        )
        addition_detail = self.detail(
            application_code=502,
            type_of_permit='New Structure',
            type_of_use='Office',
            type_of_work='Addition',
            existing_building_area=1544.0,
            new_building_area=1682.0,
            total_building_area=3226.0,
        )
        self.assertIsNone(self.collector._permit(screen_wall, screen_detail, 'commercial', {502}, self.cutoff, self.today))
        self.assertIsNone(self.collector._permit(dental_addition, addition_detail, 'commercial', {502}, self.cutoff, self.today))

"""
if marker not in test_text:
    raise SystemExit('test insertion marker not found')
test_text = test_text.replace(marker, addition + marker, 1)
tests.write_text(test_text)
print('Applied final Boise structured commercial guards and regression tests')
