from pathlib import Path
from feedgen.feed import FeedGenerator
import xml.etree.ElementTree as ET


def _ordered(rows, score_first=False, prior=()):
    # A stored snapshot has a different insertion order from a just-collected
    # ledger. Preserve prior GUID order for exact rank ties, including at the cap.
    # New tied records follow existing items; otherwise use stable permit key.
    positions={key:i for i,key in enumerate(prior)}
    stable=sorted(rows,key=lambda p:(positions.get(p.key,len(positions)),p.key))
    if score_first:
        return sorted(stable,key=lambda p:(p.score,p.issued_date),reverse=True)
    return sorted(stable,key=lambda p:(p.issued_date,p.score),reverse=True)

def _prior_guids(path):
    if not path.exists():
        return ()
    # Invalid previous feed is an integrity failure, not a fresh baseline.
    ids=[n.text for n in ET.parse(path).findall('./channel/item/guid')]
    if any(not x for x in ids) or len(ids)!=len(set(ids)):
        raise ValueError('Previous RSS feed contains missing or duplicate GUIDs')
    return ids


def _write(path,title,rows,base_url,score_first=False):
    fg=FeedGenerator(); fg.title(title); fg.link(href=base_url); fg.description(title)
    ordered = _ordered(rows, score_first=score_first, prior=_prior_guids(path))[:200]
    # feedgen prepends entries as they are added, so insert in reverse to preserve
    # the logical output order in the serialized RSS XML.
    for p in reversed(ordered):
        value = ('Valuation not reported' if p.source_name == 'City of Nampa Civic Access' and p.valuation is None else f'{p.valuation or 0:,.0f}')
        e=fg.add_entry(); e.id(p.key); e.title(f'[{p.score}] {p.jurisdiction}: {p.project_name or p.permit_type} — {p.address}'); e.link(href=p.source_url); e.description(f'{p.classification} | {p.contractor or "Contractor unknown"} | {value}')
    path.parent.mkdir(parents=True,exist_ok=True); fg.rss_file(str(path),pretty=True)


def write_all_feeds(dir,permits,base_url):
    q=[p for p in permits if p.qualifies]
    _write(dir/'new-construction.xml','Idaho New Construction',q,base_url)
    _write(dir/'multifamily.xml','Idaho Multifamily',[p for p in q if p.classification=='MULTIFAMILY'],base_url)
    _write(dir/'single-family.xml','Idaho Single Family',[p for p in q if p.classification=='SINGLE_FAMILY'],base_url)
    _write(dir/'commercial.xml','Idaho Commercial',[p for p in q if p.classification=='COMMERCIAL'],base_url)
    _write(dir/'top-opportunities.xml','Idaho Top Opportunities',[p for p in q if p.score>=35],base_url,score_first=True)
