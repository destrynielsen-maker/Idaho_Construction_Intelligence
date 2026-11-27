# Bingham County issued-report preview — independent workstream

Official index: https://www.binghamid.gov/BuildingPermitActivityReports

Source: https://www.binghamid.gov/media/Departments/PlanningandDevelopment/Building%20Permit%20Activity%20Reports/2026%20Reports/September%20BP%20Y2026.pdf

September 2026 report, page 1, viewed November 26, 2026 (Boise). The official index explicitly separates issued building permits from issued certificates of occupancy. The fixture transcribes all 43 visible rows (41 distinct Record # values), with dates through September 29, 2026. Total of the report's value column: $5735358.45; this is not a structural construction forecast. The report lacks a contractor field; owner names are intentionally omitted from the fixture. Work addresses retain source spelling. A source number may cover more than one distinct title: MFHP-26-10 has both floodplain and manufactured home observations, BPA-26-74 has floodplain and accessory building observations. Do not turn either into two permit identities or silently drop an observation. Keep county and Blackfoot city issuers separate.

The parser is a layout-mode prototype tested against a reconstruction of the observed header/rows. The original PDF could be rendered via a public source but direct byte retrieval failed in this environment, and the October report could not be retrieved. No exact PDF binary hash, live parser success, or October row-level validation is claimed. Before activation, archive the permitted source bytes, validate exact layout against multiple reports, reconcile per-period row counts and titles, review shared-number identity handling, preserve raw evidence and first seen in the production pipeline, and validate existing qualification rules without changing them. No production registration, generated data changes, ranking changes, or RSS changes. This draft is based on current main 980013827864045ab2063415d9613e5e93e273e5; no dependency on other draft branches.

Test: PYTHONPATH=src python -m unittest discover -s tests -p test_bingham_preview.py -v
