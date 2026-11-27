import unittest
from decimal import Decimal
from idaho_permits.twin_falls_county_pdf import _footer_money
from idaho_permits.twin_falls_county_pdf import _layout,_col,SEPTEMBER_STARTS,OCTOBER_STARTS

class TwinFallsPDFLayoutTests(unittest.TestCase):
    def test_distinct_report_layouts(self):
        for x, expected, permit in [(714,SEPTEMBER_STARTS,143),(760,OCTOBER_STARTS,151)]:
            with self.subTest(x=x):
                starts=_layout([{"text":"SUBTYPE","x0":x}],1533)
                self.assertEqual(starts,expected)
                self.assertEqual(_col({"x0":permit},1533,starts),1)
    def test_unknown_header_fails_closed(self):
        for x in (100,735,800):
            with self.assertRaises(ValueError):
                _layout([{"text":"SUBTYPE","x0":x}],1533)
        with self.assertRaises(ValueError):
            _layout([],1533)

    def test_observed_october_footer_word_split(self):
        self.assertEqual(_footer_money('$ 2 ,420,828.01'), Decimal('2420828.01'))
        self.assertEqual(_footer_money('$1,234.00'), Decimal('1234.00'))
        for value in ('2 420 828.01', '$2,42.00', '$1.00 $2.00', '', '-', 'total $1.00'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _footer_money(value)
