"""fast_run.py <job>   job = domain@part  (queue/<job>.txt, lines 'url' or 'n<TAB>url')
Fast lane on a fleet runner: plain-HTTP fetch -> inline CSS/fonts/images -> strip scripts -> render offline -> extract -> QA gate.
Only PASS pages are uploaded to R2 ui-library-elite/<domain>/run2/fleet__<job>/<name>/ . Everything else is logged to run2/_fleet_status/<job>.json."""
import sys, os, re, json, asyncio, shutil, time, subprocess
from pathlib import Path
from urllib.parse import urlparse
os.environ['ELITE_SCROLL_MS'] = '450'; os.environ['ELITE_BOT_WAIT'] = '6'
import requests
from inline_html import inline_page
from elite_extract import extract
import qa_lib
from playwright.async_api import async_playwright
ROOT = Path(__file__).parent; job = sys.argv[1]; domain = job.partition('@')[0]
R2 = f'r2:enterprise-canon/ui-library-elite/{domain}/run2'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
S = requests.Session(); S.headers.update({'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'}); CACHE = {}
class _R:
    def __init__(s, r): s.ok = r.ok; s._b = r.content; s.headers = r.headers
    async def body(s): return s._b
class _Req:
    async def get(s, url, timeout=15000):
        if url in CACHE: return CACHE[url]
        def go():
            try: return _R(S.get(url, timeout=timeout / 1000))
            except Exception: return None
        r = await asyncio.to_thread(go)
        if r is None: raise RuntimeError('fetch failed')
        if len(r._b) < 3_000_000: CACHE[url] = r
        return r
class _Ctx: request = _Req()
def slug(u):
    p = urlparse(u); return re.sub(r'[^A-Za-z0-9_-]+', '-', (p.path.strip('/').replace('/', '_') or 'home'))[:70]
async def main():
    q = ROOT / 'queue' / (job + '.txt')
    lines = [l.strip() for l in q.read_text(encoding='utf-8').splitlines() if l.strip()]
    items = [(int(l.split('\t')[0]) if '\t' in l else k, l.split('\t')[-1]) for k, l in enumerate(lines, 1)]
    status = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch(**({'channel': os.environ['ELITE_CHANNEL']} if os.environ.get('ELITE_CHANNEL') else {}), headless=True, args=['--disable-blink-features=AutomationControlled'])
        for n, url in items:
            name = '%04d-%s' % (n, slug(url)); out = ROOT / 'work' / job / name; fails = []; t0 = time.time()
            shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True, exist_ok=True)
            try:
                await asyncio.wait_for(extract(b, url, out, mobile=False, interact=False), timeout=600)
                qa_lib.APP_MODE = bool(re.search(r'/(cart|account|login|register|signin|sign-in)|size-chart|/collections/?$|/gift|/download|/install|/new-course-lists|t_s=marketing_website', url)); fails = qa_lib.qa(out)
            except Exception as e: fails = ['render error ' + str(e)[:80]]
            st = 'PASS' if not fails else ('NEEDS_BROWSER' if any('needs real browser' in f for f in fails) else 'FAILED')
            if out.exists():
                (out / 'qa.json').write_text(json.dumps({'status': st, 'fails': fails, 'url': url, 'section': 'fleet', 'group': job, 'source': 'fleet-live', 'mode': 'public'}), encoding='utf-8')
            if st == 'PASS':
                subprocess.run(['rclone', 'copy', str(out), f'{R2}/fleet__{job}/{name}', '-q', '--exclude', 'page_raw.html'], timeout=900)
            status.append({'n': n, 'name': name, 'url': url, 'status': st, 'fails': fails, 'sec': int(time.time() - t0)})
            print(st, name, url[:70], '; '.join(fails)[:90], flush=True)
            shutil.rmtree(out, ignore_errors=True) if st != 'PASS' else None
        await b.close()
    p = ROOT / 'work' / (job + '.json'); p.parent.mkdir(exist_ok=True); p.write_text(json.dumps(status), encoding='utf-8')
    subprocess.run(['rclone', 'copyto', str(p), f'{R2}/_fleet_status/{job}.json', '-q'])
    import collections; print('JOB DONE', dict(collections.Counter(x['status'] for x in status)))
asyncio.run(main())
