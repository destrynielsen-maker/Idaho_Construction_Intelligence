import unittest
from copy import deepcopy
from idaho_permits.twin_falls_candidate_review import review_candidates, to_candidate

def row():
    return dict(permit_number="B2026-1234", issued_date="2026-10-01",
        report_month="2026-10", source_url="https://twinfallscounty.org/test.pdf",
        source_page=1, source_pdf_sha256="a"*64, valuation_decimal="10000.00",
        permit_type="Single Family Residence", work_type="New",
        description="New detached shop", project_address="100 Example Rd",
        owner="Owner name", contractor="", parcel="P1",
        contractor_geometric_text="", contractor_source_basis="geometry")

class CandidateReviewTests(unittest.TestCase):
    def test_preserves_evidence_and_distinct_roles(self):
        r=row()
        original=deepcopy(r)
        p=to_candidate(r)
        self.assertEqual(p.key,"ID:TWIN FALLS COUNTY:B2026-1234")
        self.assertIsNone(p.contractor)
        self.assertEqual(p.owner,"Owner name")
        self.assertEqual(p.raw,original)
        self.assertEqual(r,original)
        self.assertEqual(p.stage,"PERMITTED")
    def test_conflict_is_flagged_not_suppressed(self):
        r=row()
        permits,flags=review_candidates([r])
        self.assertTrue(next(iter(permits.values())).qualifies)
        self.assertEqual(len(flags),1)
        self.assertEqual(len(permits),1)
    def test_duplicate_and_bad_evidence_rejected(self):
        with self.assertRaises(ValueError):
            review_candidates([row(),row()])
        r=row()
        r["source_pdf_sha256"]=""
        with self.assertRaises(ValueError):
            to_candidate(r)
    def test_new_residence_normal_classification(self):
        r=row()
        r["description"]="New single family dwelling"
        permits,flags=review_candidates([r])
        self.assertTrue(next(iter(permits.values())).qualifies)
        self.assertEqual(flags,[])
