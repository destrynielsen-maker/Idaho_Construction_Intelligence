# Twin Falls County offline intake (draft)

Official index: https://twinfallscounty.org/building_department/monthly_permits/
October 2026 report: https://twinfallscounty.org/wp-content/uploads/October-2026-Building-Permits-Issued-website.pdf

19 IDs manually transcribed from the two rendered source pages; latest issue October 30, 2026. Five single family residences, two manufactured homes, nine accessory structures, two agricultural exemptions, one demolition. Source subtotal $2,420,828.01. Owner names deliberately omitted; four empty contractor cells remain empty. Address text is normalized and does not determine jurisdiction. Scout's register identified the official source; this is an implementation pilot building on that work.

Run from repository root:

    PYTHONPATH=src python -m idaho_permits.county_intake tests/fixtures/twin_falls_county_2026-10.csv --expected-count 19 --output /tmp/twin-falls-preview.json
    PYTHONPATH=src python -m unittest discover -s tests -p test_county_intake.py -v

Output is exclusive-create and review-only. Tracker-shaped preview objects have qualification false and zero scores; never feed them to the production pipeline. No collector registration, production changes, automatic PDF download, or qualification mapping. A missing batch row never deletes history. Conflicts are reported rather than overwriting old facts. Source CSV hash is preserved, not a PDF hash. Original PDF bytes were not retrieved; archive and hash the source PDF, verify a second official month and manual transcription, then review identity and qualification mapping before any activation. No production authorization implied.

Caldwell city source validation is scaffolded but no Caldwell records are included. A separate city report requires matching all horizontal panels with explicit issue-date evidence. County and city must remain distinct. Do not use application date as issuance or owner as contractor.

## November 27: second source period

Official September report: https://twinfallscounty.org/wp-content/uploads/September-2026-Building-Permits-ISSUED-website.pdf

All three rendered pages reviewed: 30 distinct IDs (13/11/6 per page), latest September 30, $10,333,504.06 printed and reconciled total; five missing contractor cells. Across September and October, 49 distinct source records. Important: source subtype Single Family Residence plus work type New is not sufficient for qualification. September B2026-0550 is a detached shop at the same location as B2026-0549 (new dwelling); B2026-0516 is a log-home relocation onto a foundation; two residence additions are explicitly labeled. No qualification inferred from the count. Preserve the work-description field for real integration. New fixture omits owners and leaves ambiguous/truncated contractor spellings as printed. Added cross-period replay test and hosted read-only original-PDF verification by permit/date/page and report total. It does not claim full contractor/scope extraction or register a production collector. Current city/county index still ends October; November is not verified. Activation remains gated on actual automated row parser, raw evidence retention, current main, hosted integration and production acceptance under Nov 26 standing authorization.
