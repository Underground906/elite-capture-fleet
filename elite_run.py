"""Elite runner (2026-11-03): works through queue/<domain>.txt one page at a time, resumable.

Each page -> work/<domain>/<nnnn>-<slug>/ (elite_extract output) -> rclone move to
  r2:enterprise-canon/ui-library-elite/<domain>/pages/<nnnn>-<slug>/
Status per page appended to work/<domain>/run.jsonl (copied to R2 after every page).
Showcase pages that point at original HTML (data-original-preview) get that HTML extracted too, into artifact/.
Browser is relaunched every 12 pages and after any crash. Heavy pages that crash twice are marked 'needs_fleet'.

  python elite_run.py open-design.ai puckeditor.com ...      (domains, in order)
"""
import asyncio, json, os, re, subprocess, sys, time, shutil
from pathlib import Path
from urllib.parse import urlparse, urljoin
from elite_extract import extract

ROOT = Path(__file__).parent
R2 = 'r2:enterprise-canon/ui-library-elite'

def slug(u):
    p = urlparse(u); s = (p.netloc.split('.')[0] + '_' + p.path.strip('/').replace('/', '_')) or 'home'
    return re.sub(r'[^A-Za-z0-9_-]+', '-', s)[:90]

def rclone(*a):
    return subprocess.run(['rclone', *a], capture_output=True, text=True, timeout=900)

async def run_site(pw, job):
    # job = 'domain' (queue/domain.txt) or 'domain@part' (queue/domain@part.txt); lines are 'url' or 'n<TAB>url'
    domain, _, part = job.partition('@')
    q = ROOT / 'queue' / (job + '.txt')
    lines = [l.strip() for l in q.read_text(encoding='utf-8').splitlines() if l.strip()]
    nums = [int(l.split('	')[0]) if '	' in l else k for k, l in enumerate(lines, 1)]
    urls = [l.split('	')[-1] for l in lines]
    work = ROOT / 'work' / domain; work.mkdir(parents=True, exist_ok=True)
    log = work / ('run%s.jsonl' % ('.' + part if part else ''))
    done = {}
    if log.exists():
        for l in log.read_text(encoding='utf-8').splitlines():
            r = json.loads(l); done[r['url']] = r
    browser, since = None, 0
    for i, url in zip(nums, urls):
        if url in done and done[url]['status'] in ('ok', 'needs_fleet', 'error'): continue
        name = '%04d-%s' % (i, slug(url)); out = work / name
        rec = {'n': i, 'url': url, 'dir': name, 'started': time.strftime('%Y-%m-%d %H:%M:%S')}
        for attempt in (1, 2):
            if browser is None or since >= 12:
                if browser:
                    try: await browser.close()
                    except Exception: pass
                browser = await pw.chromium.launch(args=['--disable-dev-shm-usage', '--no-sandbox', '--js-flags=--max-old-space-size=' + os.environ.get('ELITE_HEAP', '512'), '--disable-blink-features=AutomationControlled'])
                since = 0
            try:
                shutil.rmtree(out, ignore_errors=True)
                page = await asyncio.wait_for(extract(browser, url, out), timeout=720)
                since += 1
                rec.update(status='ok', page_type_guess=page['page_type_guess'], counts=page['counts'], http=page['http'], title=page['title'], interactions=page.get('interactions'), flow=page.get('flow'), tool=page.get('tool'))
                html = (out / 'page.html').read_text(encoding='utf-8', errors='ignore')
                m = re.search(r'data-original-preview="([^"]+)"', html)
                if m:
                    try:
                        a = await asyncio.wait_for(extract(browser, urljoin(url, m.group(1)), out / 'artifact', mobile=False, interact=False), timeout=240)
                        rec['artifact'] = {'url': urljoin(url, m.group(1)), 'counts': a['counts']}
                    except Exception as e:
                        rec['artifact_error'] = str(e)[:200]
                break
            except Exception as e:
                rec.update(status='needs_fleet' if attempt == 2 else 'retry', error=str(e)[:300])
                try: await browser.close()
                except Exception: pass
                browser = None
        if rec['status'] == 'retry': rec['status'] = 'error'
        if out.exists():
            r = rclone('move', str(out), '%s/%s/pages/%s' % (R2, domain, name), '--delete-empty-src-dirs')
            if r.returncode != 0: rec['upload_error'] = r.stderr[-300:]
            shutil.rmtree(out, ignore_errors=True)
        rec['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(log, 'a', encoding='utf-8') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        rclone('copyto', str(log), '%s/%s/%s' % (R2, domain, log.name))
        print(domain, i, len(urls), rec['status'], url, flush=True)
    if browser:
        try: await browser.close()
        except Exception: pass

async def main(domains):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        for d in domains:
            await run_site(pw, d)
            (ROOT / 'work' / d.partition('@')[0] / ('DONE_' + d)).write_text(time.strftime('%Y-%m-%d %H:%M:%S'))
            print('SITE DONE', d, flush=True)

if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:]))
