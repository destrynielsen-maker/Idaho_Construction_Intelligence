# Idaho source notes

## Automated sources
- Boise Development Tracker: official City of Boise `Development_Tracker_Open_Data` FeatureServer. Updated daily and treated as an **early-lead planning source**, not an issued-building-permit source. Records retain Boise's stable record ID, project name, planning status, address, planning type, description, area and direct Accela link when available. These records are stored with `stage=PLANNING` so downstream users can distinguish pre-permit opportunities from issued permits.
- Eagle: official City of Eagle iWorQ public permit portal. The live collector reads the current permit listing, keeps only `Building Residential` / `Building Commercial` records, and checks permit-detail scope before the shared classifier can promote a record as new construction. Trade permits remain excluded. Eagle's Laserfiche weekly reports remain the official historical/backfill path.
- Coeur d'Alene: official `IssuedPermitsLastWeek` PDF; structured parser extracts permit number, owner, address, project, issued date, valuation, type, contractor and architect/draftsman when present.
- Meridian: official Construction Reports page; discovers current report PDFs and conservatively extracts only explicit new-build records with recognizable permit/date/address context.
- Nampa: official Permit Reports page; discovers weekly Permit Activity Type PDFs and uses the same conservative extraction rule.
- Kootenai County: official weekly building permit archive and report PDFs.

## Expansion queue
Canyon County is the next Treasure Valley target. Caldwell, Star, Middleton, Post Falls, Twin Falls, Pocatello and Idaho Falls remain in the public source directory and are intentionally not scraped until an unattended collection path is verified.

## Prospecting rules
Keep: new single-family, duplex/fourplex/townhome, multifamily/apartments, commercial new construction, shells, warehouse/industrial, hotel/hospitality, mixed-use.
Suppress: reroof, HVAC/mechanical replacement, plumbing/electrical, solar, signs, fences, pools, windows/doors, small remodels and tenant improvements.

The stable key is `ID:JURISDICTION:PERMIT_NUMBER`.

## Blackfoot: standalone issued-report preview (not a lead feed)

The City of Blackfoot [monthly permit reports](https://www.cityofblackfoot.org/461/Monthly-Building-Permit-Reports) currently link separate direct PDFs. The [September 2026](https://www.cityofblackfoot.org/DocumentCenter/View/2311/Building-Permit-Report-September-2026) and [October 2026](https://www.cityofblackfoot.org/DocumentCenter/View/2344/Building-Permit-Report-October-2026) files have two validated column layouts; both explicitly identify issued dates. The October report also contains a public-works facility and manufactured/replacement work, which are not private construction opportunities. Applicant is not builder/GC, and detached/twin-home permits are not proof of unit counts or independently verified new projects.

To get a read-only research preview, optionally install `pip install -r requirements.txt -r requirements-preview.txt` and run `PYTHONPATH=src python -m idaho_permits.blackfoot_preview`. Output goes to stdout only; default collection registration, dashboard, feeds, history, classification, and GitHub Actions are unchanged. Permit candidate IDs are marked manual-review only, never qualified or fed to a sales dashboard. Applicant names, addresses, and unstructured source notes are not printed. The preview fails closed on a missing/mismatched report, mixed schema, unknown issue-date layout, or date outside the published month. A future report may require another parser profile; do not infer issue date from generic “Permit Date” labels without confirmation.

Live 2026-11-26 validation: October 7 official records / 1 detached-home candidate; September 3 records / 2 twin-home configuration candidates; 10 unique official IDs; latest official issue Oct 20 (37 days before the check). No candidate became an automatically qualified lead. No contractor role or unit count was asserted. No November report was listed.
