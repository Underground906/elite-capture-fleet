"""elite_decomp_live.py - LIVE HTML decomposition (no model). 2026-11-15.

For each captured page dir: re-open the live URL in a real browser, match every captured block (by its stored box) to the DOM element,
and save a self-contained fragment (computed styles inlined, pseudo-elements, svg, local asset + font references), plus a render-vs-PNG score.

Per page -> R2 <domain>/pages/<dir>/decomp/ { fragments.jsonl.gz, fonts.css, report.json }
Assets/fonts (content-addressed) -> R2 ui-library-assets/<domain>/{img,fonts}/<sha>.<ext>

  python elite_decomp_live.py <queue-file> [--limit N]      queue file = lines of page dir names for ONE domain: first line '#domain'
"""
import asyncio, gzip, hashlib, json, os, re, shutil, subprocess, sys, time, io
from pathlib import Path
from urllib.parse import urljoin, urlparse

R2 = 'r2:enterprise-canon/ui-library-elite'
RA = 'r2:enterprise-canon/ui-library-assets'
ROOT = Path(__file__).parent
WORK = ROOT / 'dwork'

def rc(*a, timeout=900): return subprocess.run([os.environ.get('ELITE_RCLONE', 'rclone'), *a], capture_output=True, text=True, timeout=timeout)

JS = r"""
(args) => {
 const WL = ['display','position','top','right','bottom','left','float','clear','z-index','box-sizing','width','height','min-width','max-width','min-height','max-height','margin-top','margin-right','margin-bottom','margin-left',
 'padding-top','padding-right','padding-bottom','padding-left','border-top-width','border-right-width','border-bottom-width','border-left-width','border-top-style','border-right-style','border-bottom-style','border-left-style',
 'border-top-color','border-right-color','border-bottom-color','border-left-color','border-top-left-radius','border-top-right-radius','border-bottom-left-radius','border-bottom-right-radius',
 'background-color','background-image','background-size','background-position','background-repeat','box-shadow','opacity','overflow-x','overflow-y','transform','transform-origin','filter','backdrop-filter','mix-blend-mode',
 'flex-direction','flex-wrap','flex-grow','flex-shrink','flex-basis','justify-content','align-items','align-content','align-self','gap','row-gap','column-gap','order',
 'grid-template-columns','grid-template-rows','grid-column-start','grid-column-end','grid-row-start','grid-row-end','grid-auto-flow',
 'color','font-family','font-size','font-weight','font-style','line-height','letter-spacing','text-transform','text-align','text-decoration-line','text-decoration-color','white-space','text-overflow','word-break','vertical-align','visibility','cursor','object-fit','object-position','aspect-ratio','list-style-type','-webkit-text-fill-color','-webkit-background-clip','outline-style','outline-width','outline-color'];
 const INH = new Set(['color','font-family','font-size','font-weight','font-style','line-height','letter-spacing','text-transform','text-align','white-space','visibility','cursor','list-style-type','word-break','-webkit-text-fill-color']);
 const fr = document.createElement('iframe'); fr.style.cssText = 'position:absolute;left:-9999px;top:0;width:1440px;height:50px;border:0'; document.body.appendChild(fr);
 const idoc = fr.contentDocument, iwin = fr.contentWindow; const dtag = {};
 const defs = (tag) => { if (dtag[tag]) return dtag[tag]; const e = idoc.createElement(tag); if (tag === 'a') e.setAttribute('href', '#'); idoc.body.appendChild(e); const cs = iwin.getComputedStyle(e); const o = {}; for (const p of WL) o[p] = cs.getPropertyValue(p); idoc.body.removeChild(e); return dtag[tag] = o; };
 const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','LINK','META','TEMPLATE','HEAD','TITLE']);
 const abs = (u) => { try { return new URL(u, document.baseURI).href } catch (e) { return u } };
 const esc = (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
 function styleOf(el, parentCS, root, pseudo) {
   const cs = getComputedStyle(el, pseudo || null); const d = defs(pseudo ? 'span' : el.tagName.toLowerCase()); const out = [];
   for (const p of WL) {
     const v = cs.getPropertyValue(p); if (v === '') continue;
     const mb = p.match(/^border-(top|right|bottom|left)-width$/);
     if (mb) { if (cs.getPropertyValue('border-' + mb[1] + '-style') !== 'none') out.push(p + ':' + v); continue; }
     if (INH.has(p) && parentCS && !root) { if (parentCS.getPropertyValue(p) === v) continue; }
     else if (d[p] === v) continue;
     if (p === 'width' || p === 'height') continue;      // sizes come from the box below
     out.push(p + ':' + v);
   }
   return out.join(';');
 }
 function pseudoHTML(el, which, cs0) {
   const ps = getComputedStyle(el, which); const c = ps.getPropertyValue('content');
   if (!c || c === 'none' || c === 'normal') return '';
   if (ps.getPropertyValue('display') === 'none') return '';
   const txt = c.replace(/^["']|["']$/g, '');
   const w = ps.getPropertyValue('width'), h = ps.getPropertyValue('height');
   return '<span data-pseudo="' + which.slice(2) + '" style="' + esc(styleOf(el, cs0, false, which) + ';width:' + w + ';height:' + h) + '">' + (txt && txt !== '""' ? esc(txt) : '') + '</span>';
 }
 function ser(el, parentCS, root) {
   if (el.nodeType === 3) return esc(el.textContent.replace(/\s+/g, ' '));
   if (el.nodeType !== 1 || SKIP.has(el.tagName)) return '';
   const tag = el.tagName.toLowerCase(); const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
   if (cs.display === 'none') return '';
   if (r.width === 0 && r.height === 0 && cs.display !== 'contents') return '';
   const st = styleOf(el, parentCS, root) + (cs.display !== 'inline' ? ';box-sizing:border-box;width:' + Math.round(r.width) + 'px;min-height:' + Math.round(r.height) + 'px' : '');
   let at = ' data-el="' + (el.__i || '') + '"';
   if (tag === 'svg' || tag === 'SVG') { const c = el.cloneNode(true); c.setAttribute('style', 'width:' + Math.round(r.width) + 'px;height:' + Math.round(r.height) + 'px;color:' + cs.color + ';fill:' + cs.fill + ';stroke:' + cs.stroke); return c.outerHTML; }
   if (tag === 'img') { const src = el.currentSrc || el.src; return '<img' + at + ' src="' + esc(abs(src)) + '" alt="' + esc(el.alt || '') + '" style="' + esc(st) + ';width:' + Math.round(r.width) + 'px;height:' + Math.round(r.height) + 'px">'; }
   if (tag === 'video' || tag === 'canvas' || tag === 'iframe' || tag === 'picture') {
     if (tag === 'picture') { const im = el.querySelector('img'); if (im) return ser(im, cs, false); }
     const poster = tag === 'video' ? (el.poster || '') : '';
     return '<div' + at + ' data-kind="' + tag + '" style="' + esc(st) + ';width:' + Math.round(r.width) + 'px;height:' + Math.round(r.height) + 'px;background:#ddd' + (poster ? ' url(' + abs(poster) + ') center/cover' : '') + '"></div>';
   }
   for (const a of ['href','alt','aria-label','role','type','placeholder','name','for','target','title']) { const v = el.getAttribute(a); if (v !== null && v !== '') at += ' ' + a + '="' + esc(a === 'href' ? abs(v) : v) + '"'; }
   if (el.className && typeof el.className === 'string') at += ' data-cls="' + esc(el.className.slice(0, 80)) + '"';
   if (tag === 'input') { at += ' value="' + esc(el.value || '') + '"'; return '<input' + at + ' style="' + esc(st) + '">'; }
   if (tag === 'br' || tag === 'hr') return '<' + tag + at + '>';
   let inner = pseudoHTML(el, '::before', cs);
   for (const c of el.childNodes) inner += ser(c, cs, false);
   inner += pseudoHTML(el, '::after', cs);
   return '<' + tag + at + ' style="' + esc(st) + '">' + inner + '</' + tag + '>';
 }
 // index all elements with page-coordinate rects
 const all = [...document.querySelectorAll('body, body *')]; const sy = window.scrollY, sx = window.scrollX;
 const rects = all.map((e, i) => { e.__i = i; const r = e.getBoundingClientRect(); return [i, Math.round(r.left + sx), Math.round(r.top + sy), Math.round(r.width), Math.round(r.height)]; });
 const res = []; const used = new Set();
 for (const b of args.boxes) {
   let best = null, bd = 1e9;
   for (const [i, x, y, w, h] of rects) {
     const d = Math.abs(x - b.x) + Math.abs(y - b.y) + Math.abs(w - b.w) + Math.abs(h - b.h);
     if (d < bd) { bd = d; best = i; }
   }
   if (best === null || bd > 24) { res.push({ id: b.id, matched: false, dist: bd }); continue; }
   const el = all[best]; const par = el.parentElement ? getComputedStyle(el.parentElement) : null;
   let html = ''; try { html = ser(el, par, true); } catch (e) { res.push({ id: b.id, matched: false, err: String(e).slice(0, 80) }); continue; }
   res.push({ id: b.id, matched: true, dist: bd, w: b.w, h: b.h, html });
 }
 // font-face rules
 const ff = [];
 for (const ss of document.styleSheets) { let rules; try { rules = ss.cssRules; } catch (e) { ff.push({ blocked: ss.href }); continue; }
   for (const r of rules) if (r.type === CSSRule.FONT_FACE_RULE) ff.push({ css: r.cssText, base: ss.href || document.baseURI }); }
 fr.remove();
 return { res, ff, docH: document.documentElement.scrollHeight, nEl: all.length };
}
"""

def sha(s): return hashlib.sha1(s.encode()).hexdigest()[:16]

async def fetch_bytes(ctx, url, cap=6_000_000):
    try:
        r = await ctx.request.get(url, timeout=20000)
        if r.status != 200: return None, None
        b = await r.body()
        return (b if len(b) <= cap else None), r.headers.get('content-type', '')
    except Exception: return None, None

EXT = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif', 'image/svg+xml': 'svg', 'image/avif': 'avif', 'font/woff2': 'woff2', 'font/woff': 'woff',
       'application/font-woff2': 'woff2', 'application/font-woff': 'woff', 'font/ttf': 'ttf', 'font/otf': 'otf', 'application/octet-stream': 'bin'}

async def localise(ctx, site_dir, domain, frags, ffs):
    """download images (in fragments) and fonts; rewrite URLs to assets/<sha>.<ext> ; returns css text + stats"""
    img_dir = site_dir / 'img'; font_dir = site_dir / 'fonts'; img_dir.mkdir(parents=True, exist_ok=True); font_dir.mkdir(parents=True, exist_ok=True)
    urls = set()
    for f in frags:
        urls |= set(re.findall(r'src="(https?://[^"]+)"', f['html'])); urls |= set(re.findall(r'url\((https?://[^)\'" ]+)\)', f['html']))
    mp = {}; ok = fail = 0
    for u in sorted(urls)[:400]:
        b, ct = await fetch_bytes(ctx, u)
        if b is None: fail += 1; continue
        ext = EXT.get((ct or '').split(';')[0].strip()) or (Path(urlparse(u).path).suffix.lstrip('.')[:5] or 'bin'); fn = f'{sha(u)}.{ext}'
        (img_dir / fn).write_bytes(b); mp[u] = f'asset://{domain}/img/{fn}'; ok += 1
    for f in frags:
        h = f['html']
        for u, p in mp.items(): h = h.replace(u, p)
        f['html'] = h
    css = []
    for ff in ffs:
        if 'css' in ff:
            t = ff['css']
            for m in re.findall(r'url\(["\']?([^)"\']+)["\']?\)', t):
                if m.startswith('data:'): continue
                u = urljoin(ff['base'], m); b, ct = await fetch_bytes(ctx, u, 3_000_000)
                if b is None: continue
                ext = EXT.get((ct or '').split(';')[0].strip()) or (Path(urlparse(u).path).suffix.lstrip('.')[:5] or 'woff2'); fn = f'{sha(u)}.{ext}'
                (font_dir / fn).write_bytes(b); t = t.replace(m, f'asset://{domain}/fonts/{fn}')
            css.append(t)
        elif ff.get('blocked'):
            try:
                r = await ctx.request.get(ff['blocked'], timeout=15000)
                if r.status == 200:
                    txt = await r.text()
                    for blk in re.findall(r'@font-face\s*\{[^}]*\}', txt):
                        for m in re.findall(r'url\(["\']?([^)"\']+)["\']?\)', blk):
                            if m.startswith('data:'): continue
                            u = urljoin(ff['blocked'], m); b, ct = await fetch_bytes(ctx, u, 3_000_000)
                            if b is None: continue
                            ext = EXT.get((ct or '').split(';')[0].strip()) or (Path(urlparse(u).path).suffix.lstrip('.')[:5] or 'woff2'); fn = f'{sha(u)}.{ext}'
                            (font_dir / fn).write_bytes(b); blk = blk.replace(m, f'asset://{domain}/fonts/{fn}')
                        css.append(blk)
            except Exception: pass
    return '\n'.join(css), ok, fail

def ssim_score(a_path, b_path):
    try:
        from PIL import Image
        import numpy as np
        from skimage.metrics import structural_similarity as ssim
        A = Image.open(a_path).convert('L'); B = Image.open(b_path).convert('L'); W = min(400, A.width)
        A = A.resize((W, max(8, int(A.height * W / A.width)))); B = B.resize(A.size)
        return round(float(ssim(np.array(A), np.array(B))), 3)
    except Exception as e: return None

async def do_page(pw_ctx_factory, domain, dname, site_dir):
    d = WORK / domain / dname; shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
    rc('copy', f'{R2}/{domain}/pages/{dname}', str(d), '--include', 'page.json', '--include', 'blocks.json', '--include', 'crops/**', '--max-depth', '2', '-q')
    pj = json.loads((d / 'page.json').read_text('utf-8')); bj = json.loads((d / 'blocks.json').read_text('utf-8'))['blocks']
    boxes = [b for b in bj if b['w'] * b['h'] >= 4000 and b['w'] >= 40 and b['h'] >= 24]
    boxes.sort(key=lambda b: -b['w'] * b['h']); boxes = boxes[:int(os.environ.get('DECOMP_MAX_BLOCKS', '150'))]
    rep = {'page': dname, 'url': pj['url'], 'captured_height': pj.get('height'), 'started': time.strftime('%Y-%m-%d %H:%M:%S')}
    ctx = await pw_ctx_factory(); page = await ctx.new_page()
    try:
        await page.goto(pj.get('final_url') or pj['url'], wait_until='domcontentloaded', timeout=45000)
        try: await page.wait_for_load_state('networkidle', timeout=15000)
        except Exception: pass
        for y in range(0, 12000, 900): await page.evaluate(f'window.scrollTo(0,{y})'); await page.wait_for_timeout(250)
        await page.evaluate('window.scrollTo(0,0)'); await page.wait_for_timeout(1200)
        out = await page.evaluate(JS, {'boxes': [{'id': b['block_id'], 'x': b['x'], 'y': b['y'], 'w': b['w'], 'h': b['h']} for b in boxes]})
        frags = [r for r in out['res'] if r.get('matched')]
        rep.update(live_height=out['docH'], elements=out['nEl'], boxes=len(boxes), matched=len(frags), match_rate=round(len(frags) / max(1, len(boxes)), 3))
        css, ok, fail = await localise(ctx, site_dir, domain, frags, out['ff'])
        rep.update(images_ok=ok, images_failed=fail, font_rules=len([f for f in out['ff'] if 'css' in f]), fonts_blocked_sheets=len([f for f in out['ff'] if 'blocked' in f]))
        dd = d / 'decomp'; dd.mkdir(exist_ok=True)
        with gzip.open(dd / 'fragments.jsonl.gz', 'wt', encoding='utf-8') as g:
            for f in frags: g.write(json.dumps({'block_id': f['id'], 'w': f['w'], 'h': f['h'], 'match_dist': f['dist'], 'html': f['html']}, ensure_ascii=False) + '\n')
        (dd / 'fonts.css').write_text(css, encoding='utf-8')
        # render gate on up to 6 fragments
        scores = []
        for f in sorted(frags, key=lambda f: -f['w'] * f['h'])[:6]:
            crop = d / 'crops' / f"{f['id']}.png"
            if not crop.exists(): continue
            gh = dd / f"gate_{f['id']}.html"
            gh.write_text(f'<!doctype html><meta charset="utf-8"><style>{css}</style><body style="margin:0;background:#fff"><div style="width:{f["w"]}px">{f["html"]}</div>', encoding='utf-8')
            # asset:// scheme -> local files for the render gate
            html = gh.read_text(encoding='utf-8').replace(f'asset://{domain}/', str(site_dir.resolve()).replace('\\', '/') + '/')
            gh.write_text(html, encoding='utf-8')
            gp = await ctx.new_page()
            try:
                await gp.set_viewport_size({'width': int(f['w']) + 4, 'height': min(int(f['h']) + 4, 3000)})
                await gp.goto('file://' + str(gh.resolve()).replace('\\', '/'), wait_until='load', timeout=20000); await gp.wait_for_timeout(800)
                shot = dd / f"gate_{f['id']}.png"; await gp.screenshot(path=str(shot), clip={'x': 0, 'y': 0, 'width': f['w'], 'height': min(f['h'], 3000)})
                scores.append({'block': f['id'], 'ssim': ssim_score(crop, shot)})
                if len(scores) <= 2:
                    from PIL import Image
                    A = Image.open(crop).convert('RGB'); B = Image.open(shot).convert('RGB').resize(A.size); S = Image.new('RGB', (A.width * 2 + 10, A.height), 'white'); S.paste(A, (0, 0)); S.paste(B, (A.width + 10, 0)); S.thumbnail((1600, 900)); S.save(dd / f"gate_sample_{f['id']}.png")
            except Exception as e: scores.append({'block': f['id'], 'err': str(e)[:60]})
            finally: await gp.close()
            gh.unlink(missing_ok=True); (dd / f"gate_{f['id']}.png").unlink(missing_ok=True)
        rep['gate'] = scores; vals = [s['ssim'] for s in scores if s.get('ssim') is not None]
        rep['gate_median_ssim'] = sorted(vals)[len(vals) // 2] if vals else None
        rep['status'] = 'ok' if frags else 'no_match'
        (dd / 'report.json').write_text(json.dumps(rep, indent=1), encoding='utf-8')
        rc('copy', str(dd), f'{R2}/{domain}/pages/{dname}/decomp', '-q')
    except Exception as e:
        rep['status'] = 'error'; rep['error'] = str(e)[:200]
        (d / 'report.json').write_text(json.dumps(rep, indent=1), encoding='utf-8'); rc('copyto', str(d / 'report.json'), f'{R2}/{domain}/pages/{dname}/decomp/report.json', '-q')
    finally:
        await ctx.close(); shutil.rmtree(d, ignore_errors=True)
    return rep

async def main(qfile, limit):
    from playwright.async_api import async_playwright
    lines = [l.strip() for l in Path(qfile).read_text(encoding='utf-8').splitlines() if l.strip()]
    domain = lines[0].lstrip('#'); dirs = lines[1:][:limit]
    site_dir = WORK / '_assets' / domain
    async with async_playwright() as pw:
        ch = os.environ.get('ELITE_CHANNEL') or None
        br = await pw.chromium.launch(channel=ch, args=['--disable-blink-features=AutomationControlled'])
        async def fac(): return await br.new_context(viewport={'width': 1440, 'height': 900}, user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36')
        for dname in dirs:
            have = rc('lsf', f'{R2}/{domain}/pages/{dname}/decomp/report.json').stdout.strip()
            if have: print('skip', domain, dname, flush=True); continue
            t0 = time.time(); rep = await do_page(fac, domain, dname, site_dir)
            print(domain, dname, rep.get('status'), 'match', rep.get('match_rate'), 'ssim', rep.get('gate_median_ssim'), 'img', rep.get('images_ok'), round(time.time() - t0), 's', flush=True)
            rc('copy', str(site_dir), f'{RA}/{domain}', '--ignore-existing', '--transfers', '8', '-q')
        await br.close()
    shutil.rmtree(site_dir, ignore_errors=True)

if __name__ == '__main__':
    q = sys.argv[1]; lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 9999
    asyncio.run(main(q, lim))
