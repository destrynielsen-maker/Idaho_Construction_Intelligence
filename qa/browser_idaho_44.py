"""Local browser acceptance of candidate, not a deployment."""
import csv
import functools
import http.server
import io
import json
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[1]
handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(root/'public'))
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
payload=json.loads((root/'public/data/permits.json').read_text())
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width,height in [(1440,900),(390,844)]:
        page=browser.new_page(viewport={'width':width,'height':height},accept_downloads=True)
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'http://127.0.0.1:{server.server_port}/')
        expect(page.locator('#allPublished')).to_have_text(f"{len(payload['permits']):,}")
        def count(selector):return int(page.locator(selector).inner_text().replace(',',''))
        def check():
            n=count('#total')
            assert n==sum(count('#'+i) for i in ['issuedTotal','applicationTotal','planningTotal','unverifiedTotal'])
            expect(page.locator('#count')).to_contain_text(f'{n:,} matching records')
            return n
        recent=check()
        page.locator('#days').select_option('0')
        page.locator('#minScore').select_option('0')
        assert check()==len(payload['permits'])
        page.locator('#evidence').select_option('issued')
        n=check()
        assert n==count('#issuedTotal') and n>0
        with page.expect_download() as info:page.locator('#export').click()
        exported=list(csv.DictReader(io.StringIO(Path(info.value.path()).read_text(encoding='utf-8'))))
        assert len(exported)==n and all(r['date_evidence']=='issued' for r in exported)
        page.locator('#search').fill('unlikely-no-result-7e71c31')
        assert check()==0
        expect(page.locator('#valuation')).to_have_text('—')
        expect(page.locator('#export')).to_be_disabled()
        assert not errors,errors
        print(f'PASS {width}x{height}: recent={recent}, full={len(payload["permits"])}, verified-issued export={n}; zero match behavior',flush=True)
        page.close()
    browser.close()
server.shutdown()
