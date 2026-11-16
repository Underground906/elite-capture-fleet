"""clean_shots.py - fresh screenshots of the SAVED page.html with cookie banners / consent overlays / chat widgets removed.
No live re-capture: the stored HTML is rendered (scripts blocked so banners can't come back), overlays removed, full-page PNG saved.
Per page -> R2 <domain>/pages/<dir>/page_clean.png (only when something was removed) + clean.json {removed:n, tags:[...]}.
  python clean_shots.py <queue-file>     (first line '#domain', then page dir names)
"""
import asyncio, json, os, shutil, subprocess, sys
from pathlib import Path
from playwright.async_api import async_playwright
R2 = 'r2:enterprise-canon/ui-library-elite'
WORK = Path(__file__).parent / 'cwork'
def rc(*a, timeout=600): return subprocess.run(['rclone', *a], capture_output=True, text=True, timeout=timeout)
KILL = """(()=>{const sel=['#usercentrics-root','#usercentrics-cmp-ui','[id*=cookie i]','[class*=cookie i]','[id*=consent i]','[class*=consent i]','[id*=onetrust i]','[class*=onetrust i]','[id^=CybotCookiebotDialog]','[id*=truste i]','[id*=didomi i]','[class*=didomi i]','[id*=osano i]','[class*=osano i]','[id*=termly i]','[class*=termly i]','[id*=iubenda i]','[class*=iubenda i]','[id*=gdpr i]','[class*=gdpr i]','[aria-label*=cookie i]','[aria-label*=consent i]','[id*=intercom i]','[class*=intercom i]','[id*=drift i]','[id*=crisp i]','[class*=crisp-client i]','[id*=hubspot-messages i]','[id*=chat-widget i]','[class*=chat-widget i]','[id*=livechat i]','[id*=tidio i]','[id*=zendesk i]','[id*=launcher i][role=button]','iframe[title*=chat i]','iframe[title*=messenger i]','[class*=cc-window]'];
const keep=document.querySelector('main,h1');const tags=[];let n=0;
for(const s of sel)document.querySelectorAll(s).forEach(e=>{if(e===document.body||e===document.documentElement||(keep&&e.contains(keep)))return;tags.push(s.slice(0,30));e.remove();n++});
for(const e of document.querySelectorAll('body *')){const c=getComputedStyle(e);if(c.position==='fixed'&&parseFloat(c.opacity)>0&&e.offsetWidth>=innerWidth*0.95&&e.offsetHeight>=innerHeight*0.95&&!e.querySelector('main,h1,nav,header')&&(e.textContent||'').trim().length<400){tags.push('fixed-overlay');e.remove();n++}}
document.documentElement.style.overflow='auto';document.body.style.overflow='auto';document.body.style.position='static';document.body.classList.remove('modal-open','no-scroll','overflow-hidden');
return {n,tags:[...new Set(tags)]}})()"""
async def one(ctx, site, d):
    w = WORK / site / d; shutil.rmtree(w, ignore_errors=True); w.mkdir(parents=True)
    rc('copy', f'{R2}/{site}/pages/{d}', str(w), '--include', 'page.html', '--include', 'page.json', '-q')
    try:
        url = json.load(open(w / 'page.json', encoding='utf-8'))['url']; body = open(w / 'page.html', encoding='utf-8', errors='ignore').read()
    except Exception as e: print('skip', site, d, e, flush=True); return
    pg = await ctx.new_page()
    try:
        await pg.route('**/*', lambda r: r.abort() if r.request.resource_type in ('script', 'xhr', 'fetch', 'websocket', 'eventsource', 'media') else r.continue_())
        await pg.route(url, lambda r: r.fulfill(status=200, content_type='text/html; charset=utf-8', body=body))
        await pg.goto(url, wait_until='load', timeout=45000); await pg.wait_for_timeout(1200)
        res = await pg.evaluate(KILL)
        out = {'removed': res['n'], 'tags': res['tags']}
        if res['n'] > 0:
            await pg.screenshot(path=str(w / 'page_clean.png'), full_page=True, timeout=60000)
            rc('copyto', str(w / 'page_clean.png'), f'{R2}/{site}/pages/{d}/page_clean.png', '-q')
        (w / 'clean.json').write_text(json.dumps(out), encoding='utf-8'); rc('copyto', str(w / 'clean.json'), f'{R2}/{site}/pages/{d}/clean.json', '-q')
        print('ok', site, d, res['n'], flush=True)
    except Exception as e: print('fail', site, d, str(e)[:80], flush=True)
    finally: await pg.close(); shutil.rmtree(w, ignore_errors=True)
async def main(qf):
    lines = [l.strip() for l in open(qf, encoding='utf-8') if l.strip()]; site = lines[0].lstrip('#'); dirs = lines[1:]
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(viewport={'width': 1440, 'height': 900})
        for d in dirs: await one(ctx, site, d)
        await b.close()
asyncio.run(main(sys.argv[1]))
