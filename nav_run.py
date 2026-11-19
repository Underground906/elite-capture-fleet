"""nav_run.py <domain>  - real-browser link discovery: home + header/footer/mega-menu links + one level deeper. Writes R2 <domain>/run2/_nav/links.json"""
import sys, os, re, json, asyncio, subprocess
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright
dom = sys.argv[1].partition('@')[0]; host = dom.split('.')[0]
JS = """()=>[...document.querySelectorAll('a[href]')].map(a=>({u:a.href.split('#')[0],t:(a.innerText||a.getAttribute('aria-label')||'').trim().replace(/\s+/g,' ').slice(0,60),a:a.closest('header,nav')?'header':(a.closest('footer')?'footer':'body')})).filter(x=>x.u.startsWith('http'))"""
async def main():
    found = {}
    async with async_playwright() as pw:
        b = await pw.chromium.launch(**({'channel': os.environ['ELITE_CHANNEL']} if os.environ.get('ELITE_CHANNEL') else {}), headless=True)
        c = await b.new_context(viewport={'width': 1440, 'height': 900}); p = await c.new_page()
        async def grab(u, depth):
            try: await p.goto(u, wait_until='domcontentloaded', timeout=60000); await p.wait_for_timeout(5000)
            except Exception: return []
            try:
                for sel in ('header button', 'nav button', '[aria-haspopup]'):          # open menus so mega-menu links render
                    for el in (await p.query_selector_all(sel))[:8]:
                        try: await el.hover(timeout=500); await p.wait_for_timeout(150)
                        except Exception: pass
            except Exception: pass
            L = await p.evaluate(JS); out = []
            for x in L:
                if host in urlparse(x['u']).netloc and not re.search(r'\.(pdf|png|jpg|svg|css|js)(\?|$)', x['u']):
                    k = x['u'].rstrip('/')
                    if k not in found: found[k] = {'url': x['u'], 'label': x['t'], 'area': x['a'], 'depth': depth}; out.append(x['u'])
            return out
        top = await grab('https://www.' + dom + '/', 0) or await grab('https://' + dom + '/', 0)
        for u in [u for u in top if found[u.rstrip('/')]['area'] in ('header', 'footer')][:25]: await grab(u, 1)
        await b.close()
    f = '/tmp/links.json'; json.dump(list(found.values()), open(f, 'w'))
    subprocess.run(['rclone', 'copyto', f, f'r2:enterprise-canon/ui-library-elite/{dom}/run2/_nav/links.json', '-q'])
    print(dom, len(found), 'links')
asyncio.run(main())
