from __future__ import annotations
from io import BytesIO
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

def get(url, timeout=45):
    r=requests.get(url,timeout=timeout,headers={'User-Agent':'IdahoConstructionIntelligence/0.1 public-permit-research'}); r.raise_for_status(); return r

def pdf_text(content: bytes) -> str:
    reader=PdfReader(BytesIO(content))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)

def discover_links(url, include=()):
    r=get(url); soup=BeautifulSoup(r.text,'html.parser'); out=[]
    from urllib.parse import urljoin
    for a in soup.find_all('a',href=True):
        label=' '.join(a.stripped_strings)
        href=urljoin(url,a['href'])
        if not include or any(x.lower() in (label+' '+href).lower() for x in include): out.append((label,href))
    return out
