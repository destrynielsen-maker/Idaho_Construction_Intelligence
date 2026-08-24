from __future__ import annotations
from io import BytesIO
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

BROWSER_HEADERS={
    'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36',
    'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.7',
    'Accept-Language':'en-US,en;q=0.9',
}

def get(url, timeout=45, referer=None):
    headers=dict(BROWSER_HEADERS)
    if referer: headers['Referer']=referer
    r=requests.get(url,timeout=timeout,headers=headers,allow_redirects=True)
    r.raise_for_status()
    return r

def pdf_text(content: bytes) -> str:
    reader=PdfReader(BytesIO(content))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)

def discover_links(url, include=()):
    r=get(url)
    soup=BeautifulSoup(r.text,'html.parser')
    out=[]
    for a in soup.find_all('a',href=True):
        label=' '.join(a.stripped_strings)
        href=urljoin(r.url,a['href'])
        hay=(label+' '+href).lower()
        if not include or any(x.lower() in hay for x in include): out.append((label,href))
    return out
