import unittest
from decimal import Decimal
from idaho_permits.twin_falls_county_pdf import _footer_money, _header_bottom, contractor_flow_candidates, _validate_contractor_flow, _clean_contractor_text
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

    def test_first_record_parcel_does_not_extend_header(self):
        words=[{"text":"DAT_ISSUED","bottom":102},
               {"text":"Parcel","bottom":100},
               {"text":"Parcel","bottom":134}]
        self.assertAlmostEqual(_header_bottom(words,{"top":145},True),102.1)
        with self.assertRaises(ValueError):
            _header_bottom(words[1:],{"top":145},True)
        self.assertEqual(_header_bottom([],{"top":145},False),0.1)

    def test_content_order_candidate_stays_in_permit_and_column(self):
        class Page:
            width=1533
            def extract_words(self, **kwargs):
                self.kwargs=kwargs
                return [{"text":t,"x0":x} for t,x in [
                    ("B2026-0627",151),("OWNER",228),("KNS",322),
                    ("CONSTRUCTI",322),("ON INC.",322),("ADDRESS",664),
                    ("B2026-0560",151),("CNR",322),("CONSTRUCTION",322),
                    ("IDAHO, LLC",322),("HANSEN",664)]]
        self.assertEqual(contractor_flow_candidates(Page(),OCTOBER_STARTS),
                         {"B2026-0627":"KNS CONSTRUCTI ON INC.","B2026-0560":"CNR CONSTRUCTION IDAHO, LLC"})

    def test_flow_requires_every_anchor_in_spatial_order(self):
        values={"B2026-0627":"KNS CONSTRUCTI ON INC.",
                "B2026-0560":"CNR CONSTRUCTI ON IDAHO, LLC"}
        self.assertEqual(_validate_contractor_flow(values,list(values)),values)
        for ids in ([],["B2026-0627"],["B2026-0560","B2026-0627"],
                    ["B2026-0627","B2026-9999"]):
            with self.assertRaises(ValueError):
                _validate_contractor_flow(values,ids)
        self.assertEqual(_clean_contractor_text(values["B2026-0627"]),"KNS CONSTRUCTION INC.")
        self.assertEqual(_clean_contractor_text(values["B2026-0560"]),"CNR CONSTRUCTION IDAHO, LLC")
        self.assertEqual(_clean_contractor_text(""),"")
