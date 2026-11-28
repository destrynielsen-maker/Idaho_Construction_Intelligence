"""Independent, offline acceptance gate for Nampa PR #47's November control.

Run against an isolated candidate replay of the seven known November permits,
not a citywide production run. No network, source changes or publication.
The hosted preview proved IDs, issue dates and contractor names, not addresses,
case URLs, classifications or valuations in its exported JSON. Candidate
evidence must supply the first three separately; valuation must remain null
for this particular replay unless a separately reviewed value fixture exists.
"""
import json
import math
import re
import sys
import unittest
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse
from idaho_permits.models import Permit
from idaho_permits.classify import classify_permit
import xml.etree.ElementTree as ET

EXPECTED = {
    "RES-19105-2026": ("2026-11-23", "Richmond American Homes of Idaho INC"),
    "RES-19090-2026": ("2026-11-23", None),
    "RES-18986-2026": ("2026-11-24", "Hayden Homes Idaho LLC"),
    "RES-18985-2026": ("2026-11-24", "Hayden Homes Idaho LLC"),
    "RES-19111-2026": ("2026-11-23", "Hubble Homes LLC"),
    "RES-19089-2026": ("2026-11-24", "Richmond American Homes of Idaho INC"),
    "RES-19147-2026": ("2026-11-24", "Richmond American Homes of Idaho INC"),
}
KEYS = {"ID:NAMPA:" + n for n in EXPECTED}
MIXED_LABEL = "residential (new single family dwelling, townhouse, and/or duplex)"

def require(condition, message):
    if not condition:
        raise AssertionError(message)

def keyed(rows):
    result = {r["key"]: r for r in rows}
    require(len(rows) == len(result), "duplicate permit identity")
    return result

def stable(r):
    return {k: v for k, v in r.items() if k != "last_seen_at"}

def audit_ledgers(before, after, prior_leads, next_leads):
    a, b = keyed(before), keyed(after)
    old_public, public = keyed(prior_leads), keyed(next_leads)
    require(not (KEYS & a.keys()), "control already present; use earlier baseline")
    require(set(b) - set(a) == KEYS and set(a) <= set(b),
            "isolated replay must add exactly seven identities and lose none")
    for k, r in a.items():
        require(stable(r) == stable(b[k]), "existing evidence changed: " + k)
    require(set(public) == set(old_public) | KEYS, "published membership delta")
    for k, r in old_public.items():
        require(stable(r) == stable(public[k]), "existing published row changed: " + k)
    case_links = set()
    for n, (date, contractor) in EXPECTED.items():
        k = "ID:NAMPA:" + n
        r = b[k]
        require(r["state"] == "ID" and r["jurisdiction"] == "Nampa" and
                r["permit_number"] == n and r["issued_date"] == date,
                "identity/date mismatch: " + k)
        require(r.get("contractor") == contractor, "contractor mismatch: " + k)
        require(r.get("valuation") is None, "unverified value in preview replay: " + k)
        require(r.get("stage") == "PERMITTED" and
                r.get("status") in ("Issued", "Finaled", "Finalized"),
                "issuance not established: " + k)
        require(bool(r.get("address", "").strip()) and bool(r.get("raw")),
                "missing case-level evidence: " + k)
        u = urlparse(r.get("source_url", ""))
        require(u.scheme == "https" and u.netloc == "nampaid-energovpub.tylerhost.net"
                and re.fullmatch(r"/apps/selfservice(?:/NampaIDProd)?/?", u.path, re.I)
                and not u.query and re.fullmatch(r"/permit/[0-9a-f-]{36}", u.fragment, re.I),
                "missing official case link: " + k)
        require(u.fragment.lower() not in case_links, "case link reused by another identity: " + k)
        case_links.add(u.fragment.lower())
        scope = r["raw"].get("scope", "").strip()
        single = re.match(r"NEW\s+(?:SFD|SINGLE[- ]FAMILY)\b", scope, re.I)
        multi = re.match(r"NEW\s+(?:TOWN(?:HOUSE|HOME)|DUPLEX)\b", scope, re.I)
        require(bool(single or multi), "explicit case scope missing: " + k)
        require(r.get("classification") == ("SINGLE_FAMILY" if single else "MULTIFAMILY"),
                "classification differs from case scope: " + k)
        require(MIXED_LABEL not in r.get("permit_type", "").lower(),
                "generic mixed search label would misclassify dwellings: " + k)
        require(r.get("qualifies") is True and r.get("classification") in
                ("SINGLE_FAMILY", "MULTIFAMILY") and bool(r.get("first_seen_at")),
                "new dwelling failed existing qualification: " + k)
        # Verify candidate classification and scoring with the unchanged production
        # implementation, rather than trusting self-reported candidate fields.
        replay = classify_permit(Permit.from_dict(r))
        for field in ('classification', 'qualifies', 'score', 'new_construction_confidence'):
            require(getattr(replay, field) == r.get(field),
                    'production classifier/score mismatch: ' + field + ': ' + k)
        require(stable(public[k]) == stable(r), "public evidence differs: " + k)
    return [b[k] for k in sorted(KEYS)]

def audit_builders(before, after, added):
    def map_rows(rows):
        d = {r["contractor"]: r for r in rows}
        require(len(d) == len(rows), "duplicate builder ranking identity")
        return d
    a, b = map_rows(before), map_rows(after)
    expected = {k: dict(v) for k, v in a.items()}
    for r in added:
        name = r.get("contractor")
        if not name:
            continue
        v = expected.setdefault(name, {"contractor": name, "count": 0,
                                        "score_total": 0, "valuation_total": 0})
        v["count"] += 1
        v["score_total"] += r["score"]
        v["valuation_total"] += r["valuation"] or 0
    require(set(expected) == set(b), "unrelated builder membership change")
    for k, v in expected.items():
        require(v["count"] == b[k]["count"] and v["score_total"] == b[k]["score_total"]
                and math.isclose(v["valuation_total"], b[k]["valuation_total"], abs_tol=0.01, rel_tol=0),
                "builder delta not explained by new permits: " + k)

def rss(path):
    result = {}
    for item in ET.parse(path).findall("./channel/item"):
        guid = item.findtext("guid")
        require(bool(guid) and guid not in result, "missing/duplicate RSS identity")
        item.tail = None  # RSS item content excludes indentation between sibling items.
        result[guid] = ET.tostring(item, encoding="unicode")
    return result

def audit_feeds(before, after):
    files = {p.name for p in before.glob("*.xml")}
    require(len(files) == 5 and files == {p.name for p in after.glob("*.xml")}, "RSS file set changed")
    for f in files:
        a, b = rss(before/f), rss(after/f)
        new, lost = set(b)-set(a), set(a)-set(b)
        require(new <= KEYS, "unrelated new RSS identity: " + f)
        require(len(lost) <= len(new) and (not lost or len(b) == 200),
                "RSS loss not explained by feed cap: " + f)
        require(all(a[k] == b[k] for k in a.keys() & b.keys()),
                "existing RSS content changed: " + f)
    require(KEYS <= rss(after/"new-construction.xml").keys(),
            "November control missing from newest construction feed")

def audit_paths(before, after):
    def load(root, path):
        return json.loads((root/path).read_text(encoding="utf-8"))
    new = audit_ledgers(load(before,"data/permits.json")["permits"],
                        load(after,"data/permits.json")["permits"],
                        load(before,"public/data/permits.json")["permits"],
                        load(after,"public/data/permits.json")["permits"])
    audit_builders(load(before,"public/data/builders.json"), load(after,"public/data/builders.json"), new)
    audit_feeds(before/"public/feeds", after/"public/feeds")
    return {"new_records": len(new), "new_published": len(new),
            "contractor_counts": dict(Counter(r["contractor"] for r in new if r["contractor"])),
            "valuation_unknown": len(new), "production_writes": 0}

class NampaReleaseGateTests(unittest.TestCase):
    # Synthetic address, case URL, scope, status and score: test the gate,
    # NOT proof of those fields on the actual municipal records.
    def setUp(self):
        self.old = [{"key":"ID:NAMPA:OLD","raw":{"source":"original"},"first_seen_at":"old"}]
        self.new = [
            {"key":"ID:NAMPA:"+n,"state":"ID","jurisdiction":"Nampa","permit_number":n,
             "issued_date":date,"contractor":name,"valuation":None,"stage":"PERMITTED",
             "status":"Issued","address":"TEST ADDRESS","raw":{"scope":"NEW SFD TEST FIXTURE"},
             "source_url":"https://nampaid-energovpub.tylerhost.net/Apps/SelfService#/permit/00000000-0000-0000-0000-"+n[4:9].zfill(12),
             "permit_type":"New Residential","source_name":"Nampa", "qualifies":True,"classification":"SINGLE_FAMILY",
             "new_construction_confidence":"HIGH",
             "first_seen_at":"test","score":20 if name else 15}
            for n,(date,name) in EXPECTED.items()]
    def run_gate(self):
        return audit_ledgers(self.old,self.old+self.new,self.old,self.old+self.new)
    def test_expected_delta(self):
        self.assertEqual(len(self.run_gate()),7)
        builders = [{"contractor":n,"count":count,"score_total":count*20,"valuation_total":0}
                    for n,count in Counter(r["contractor"] for r in self.new if r["contractor"]).items()]
        audit_builders([], builders, self.new)
        builders[0]["valuation_total"] = 1
        with self.assertRaises(AssertionError):
            audit_builders([], builders, self.new)
    def test_no_generic_mixed_permit_label(self):
        self.new[0]["permit_type"] = MIXED_LABEL
        with self.assertRaisesRegex(AssertionError,"mixed search label"):
            self.run_gate()
    def test_case_scope_and_distinct_links(self):
        self.new[0]["classification"] = "MULTIFAMILY"
        with self.assertRaisesRegex(AssertionError,"classification differs"):
            self.run_gate()
        self.new[0]["classification"] = "SINGLE_FAMILY"
        self.new[0]["source_url"] = self.new[1]["source_url"]
        with self.assertRaisesRegex(AssertionError,"case link reused"):
            self.run_gate()
    def test_no_invented_valuation_or_contractor(self):
        self.new[0]["valuation"] = 0
        with self.assertRaisesRegex(AssertionError,"unverified value"):
            self.run_gate()
        self.new[0]["valuation"] = None
        self.new[1]["contractor"] = "Unknown Owner"
        with self.assertRaisesRegex(AssertionError,"contractor mismatch"):
            self.run_gate()
    def test_actual_production_classifier_and_score(self):
        self.new[0]['score'] = 99
        with self.assertRaisesRegex(AssertionError, 'production classifier/score mismatch: score'):
            self.run_gate()
        self.new[0]['score'] = 20
        self.new[0]['permit_type'] = 'Residential'
        with self.assertRaisesRegex(AssertionError, 'production classifier/score mismatch'):
            self.run_gate()
    def test_missing_and_duplicate_fail(self):
        r = self.new.pop()
        with self.assertRaises(AssertionError):
            self.run_gate()
        self.new.extend([r,r])
        with self.assertRaisesRegex(AssertionError,"duplicate"):
            self.run_gate()
    def test_original_evidence_preserved(self):
        corrupt = [{"key":"ID:NAMPA:OLD","raw":{},"first_seen_at":"old"}]
        with self.assertRaisesRegex(AssertionError,"existing evidence changed"):
            audit_ledgers(self.old,corrupt+self.new,self.old,corrupt+self.new)

if __name__ == "__main__":
    if len(sys.argv) == 3:
        print(json.dumps(audit_paths(Path(sys.argv[1]),Path(sys.argv[2])), indent=2))
    else:
        unittest.main()
