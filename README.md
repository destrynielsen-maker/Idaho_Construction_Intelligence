# Idaho Construction Intelligence

A browser-accessible Idaho construction lead feed built from public building-permit and planning sources.

The app follows the same operating model as the Utah Construction Intelligence project: collect public records, normalize them, deduplicate them with stable keys, classify and score sales opportunities, publish RSS feeds, and generate a static dashboard for GitHub Pages.

## Automated v0.1 collectors

- Coeur d'Alene — weekly issued permits
- Meridian — official construction report page / report discovery
- Nampa — official permit report page / report discovery

## Rep research directory

The dashboard also carries direct research links for Boise, Eagle, Canyon County, Caldwell, Star, Middleton, Post Falls, Twin Falls, Pocatello, and Idaho Falls. These are intentionally retained even when the public system is better for human research than unattended collection.

## Generated outputs

- `public/index.html` — browser dashboard
- `public/feeds/new-construction.xml`
- `public/feeds/multifamily.xml`
- `public/feeds/single-family.xml`
- `public/feeds/commercial.xml`
- `public/feeds/top-opportunities.xml`
- `public/data/permits.json`
- `public/data/builders.json`
- `public/data/sources.json`
- `data/permits.json` — persistent history for deduplication

Stable record key:

```text
STATE:JURISDICTION:PERMIT_NUMBER
```

## Run locally

Requires Python 3.12+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# Windows PowerShell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python -m idaho_permits.main
```

Then serve the `public` folder:

```bash
python -m http.server 8000 --directory public
```

## GitHub Pages deployment

Set **Settings → Pages → Source** to **GitHub Actions**. The included workflow runs the collector, commits refreshed persistent data when it changes, and publishes `public/` to Pages. It is also scheduled every six hours.

See `docs/SOURCE_NOTES.md` for source-specific behavior and limitations.
