# Idaho source notes

## Automated sources
- Boise Development Tracker: official City of Boise `Development_Tracker_Open_Data` FeatureServer. Updated daily and treated as an **early-lead planning source**, not an issued-building-permit source. Records retain Boise's stable record ID, project name, planning status, address, planning type, description, area and direct Accela link when available. These records are stored with `stage=PLANNING` so downstream users can distinguish pre-permit opportunities from issued permits.
- Coeur d'Alene: official `IssuedPermitsLastWeek` PDF; structured parser extracts permit number, owner, address, project, issued date, valuation, type, contractor and architect/draftsman when present.
- Meridian: official Construction Reports page; discovers current report PDFs and conservatively extracts only explicit new-build records with recognizable permit/date/address context.
- Nampa: official Permit Reports page; discovers weekly Permit Activity Type PDFs and uses the same conservative extraction rule.
- Kootenai County: official weekly building permit archive and report PDFs.

## Expansion queue
Eagle and Canyon County are the next Treasure Valley targets. Caldwell, Star, Middleton, Post Falls, Twin Falls, Pocatello and Idaho Falls remain in the public source directory and are intentionally not scraped until an unattended collection path is verified.

## Prospecting rules
Keep: new single-family, duplex/fourplex/townhome, multifamily/apartments, commercial new construction, shells, warehouse/industrial, hotel/hospitality, mixed-use.
Suppress: reroof, HVAC/mechanical replacement, plumbing/electrical, solar, signs, fences, pools, windows/doors, small remodels and tenant improvements.

The stable key is `ID:JURISDICTION:PERMIT_NUMBER`.
