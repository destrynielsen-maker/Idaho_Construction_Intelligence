from pathlib import Path
from feedgen.feed import FeedGenerator


def _ordered(rows, score_first=False):
    if score_first:
        return sorted(rows, key=lambda x: (x.score, x.issued_date), reverse=True)
    return sorted(rows, key=lambda x: (x.issued_date, x.score), reverse=True)


def _write(path,title,rows,base_url,score_first=False):
    fg=FeedGenerator(); fg.title(title); fg.link(href=base_url); fg.description(title)
    ordered = _ordered(rows, score_first=score_first)[:200]
    # feedgen prepends entries as they are added, so insert in reverse to preserve
    # the logical output order in the serialized RSS XML.
    for p in reversed(ordered):
        e=fg.add_entry(); e.id(p.key); e.title(f'[{p.score}] {p.jurisdiction}: {p.project_name or p.permit_type} — {p.address}'); e.link(href=p.source_url); e.description(f'{p.classification} | {p.contractor or "Contractor unknown"} | {p.valuation or 0:,.0f}')
    path.parent.mkdir(parents=True,exist_ok=True); fg.rss_file(str(path),pretty=True)


def write_all_feeds(dir,permits,base_url):
    q=[p for p in permits if p.qualifies]
    _write(dir/'new-construction.xml','Idaho New Construction',q,base_url)
    _write(dir/'multifamily.xml','Idaho Multifamily',[p for p in q if p.classification=='MULTIFAMILY'],base_url)
    _write(dir/'single-family.xml','Idaho Single Family',[p for p in q if p.classification=='SINGLE_FAMILY'],base_url)
    _write(dir/'commercial.xml','Idaho Commercial',[p for p in q if p.classification=='COMMERCIAL'],base_url)
    _write(dir/'top-opportunities.xml','Idaho Top Opportunities',[p for p in q if p.score>=35],base_url,score_first=True)
