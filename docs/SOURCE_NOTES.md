# Idaho source notes

## Automated in v0.1
- Coeur d'Alene: official `IssuedPermitsLastWeek` PDF; structured parser extracts permit number, owner, address, project, issued date, valuation, type, contractor and architect/draftsman when present.
- Meridian: official Construction Reports page; discovers current report PDFs and conservatively extracts only explicit new-build records with recognizable permit/date/address context.
- Nampa: official Permit Reports page; discovers weekly Permit Activity Type PDFs and uses the same conservative extraction rule.

## Directory / rep-research sources
Boise, Eagle, Canyon County, Caldwell, Star, Middleton, Post Falls, Twin Falls, Pocatello and Idaho Falls are included in the public source directory. They are intentionally not scraped in v0.1 where the public interface is interactive, GIS-heavy, login/session oriented, or otherwise less reliable for unattended collection.

## Prospecting rules
Keep: new single-family, duplex/fourplex/townhome, multifamily/apartments, commercial new construction, shells, warehouse/industrial, hotel/hospitality, mixed-use.
Suppress: reroof, HVAC/mechanical replacement, plumbing/electrical, solar, signs, fences, pools, windows/doors, small remodels and tenant improvements.

The stable key is `ID:JURISDICTION:PERMIT_NUMBER`.
