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

## Evidence gates: Eagle, Nampa and Meridian
- **Eagle:** A dashboard lead requires a canonical numeric permit ID, verified issuance evidence (not a generic listing date), and supported new-construction scope. Legacy listing-only rows lacking verified issuance remain in the historical store, but no longer qualify for dashboard/feeds. A public portal error is a source outage, not evidence of zero issues. Anonymous iWorQ list access returned 403 during verification; the city’s Laserfiche weekly archive remains a manual fallback. Only explicitly labeled builder/general-contractor roles are used; trade contractors cannot stand in for a builder.
- **Nampa:** Use the official Permit Reports index and City-linked weekly PDF filenames/title/period only. An HTTP-successful but old document is reported stale, not current. Map named building-contractor organizations only where the labeled role, associated company column, and permit match; otherwise leave the builder unknown. The City’s Citizen Connect bulletin describes a manual export, not a verified unattended API. Do not substitute guessed document IDs or protected endpoints.
- **Meridian:** Discover current issued-permit PDFs from the [City’s new Construction Reports URL](https://about.meridiancity.org/community-development/building/construction-reports/), with vetted City-hosted report URLs as backup. Report period and newest observed issue date are independent. Deduplicate by jurisdiction/permit ID; preserve the earliest recorded first-seen timestamp. The City's Contractor column is reported as labeled, not independently verified as a GC.
- **Rollback:** Next run uses the currently merged code; revert the reviewed code commit to remove these gates. If restoring exact dashboard/feeds or prospect ranking, restore verified pre-run generated artifacts via the maintainer’s normal publication workflow, not by deleting or resetting stored permit history.

Eagle's historical-research panel is a separate narrow export, not an issuance or
lead dataset. It lists only legacy entries that previously qualified but lack
verified issuance evidence. The original record remains in the permit store;
the export omits builder/GC claims, scores and prospect rankings. Unavailable
sources have unknown counts, while stale/degraded counts describe only the
observed sample, not the market. An available report can have a true zero.
