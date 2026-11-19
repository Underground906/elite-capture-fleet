"""inline_html.py - make page.html a self-contained file that renders on its own.
inline_page(pg, out): called right after the live page is captured. Keeps the original as page_raw.html and writes
page.html with: stylesheets inlined, url() fonts/images in CSS as data URIs, <img>/<source> images as data URIs (size capped),
absolute base URLs, scripts removed (static snapshot). Returns stats dict. Also: verify_render() renders the saved file alone
and compares it with page.png."""
import re, base64, mimetypes, html as _h
from urllib.parse import urljoin
MAXB = 600_000          # biggest single asset inlined
MAXTOTAL = 18_000_000   # per page budget

async def _get(ctx, url):
    try:
        r = await ctx.request.get(url, timeout=15000)
        if not r.ok: return None, None
        b = await r.body(); ct = (r.headers.get('content-type') or '').split(';')[0]
        return b, ct
    except Exception:
        return None, None

def _mime(url, ct):
    if ct and '/' in ct and ct != 'application/octet-stream': return ct
    return mimetypes.guess_type(url.split('?')[0])[0] or 'application/octet-stream'

async def inline_page(pg, out, raw=None, base=None, ctx=None):
    ctx = ctx or pg.context; base = base or pg.url; st = {'css': 0, 'css_missing': 0, 'assets': 0, 'bytes': 0}
    if raw is None:
        raw = await pg.content()
        (out / 'page_raw.html').write_text(raw, encoding='utf-8')
    cache = {}
    async def data_uri(u):
        if u.startswith('data:') or not u.startswith('http'): return None
        if u in cache: return cache[u]
        if st['bytes'] > MAXTOTAL: return None
        b, ct = await _get(ctx, u)
        if not b or len(b) > MAXB: cache[u] = None; return None
        st['bytes'] += len(b); st['assets'] += 1
        cache[u] = 'data:%s;base64,%s' % (_mime(u, ct), base64.b64encode(b).decode()); return cache[u]
    async def fix_css(css, cbase):
        # @import first, then url(...)
        for m in list(re.finditer(r'@import\s+(?:url\()?["\']?([^"\')\s;]+)["\']?\)?[^;]*;', css)):
            u = urljoin(cbase, m.group(1)); b, _ = await _get(ctx, u)
            sub = await fix_css(b.decode('utf-8', 'ignore'), u) if b else ''
            css = css.replace(m.group(0), sub)
        out_parts, pos = [], 0
        for m in re.finditer(r'url\(\s*["\']?([^"\')]+)["\']?\s*\)', css):
            out_parts.append(css[pos:m.start()]); pos = m.end()
            u = urljoin(cbase, m.group(1).strip()); d = await data_uri(u)
            out_parts.append('url("%s")' % (d or u))
        out_parts.append(css[pos:]); return ''.join(out_parts)
    html = raw
    # 1) stylesheets
    for m in list(re.finditer(r'<link\b[^>]*rel=["\']?stylesheet["\']?[^>]*>', html, re.I)):
        tag = m.group(0); hm = re.search(r'href=["\']([^"\']+)["\']', tag)
        if not hm: continue
        u = urljoin(base, _h.unescape(hm.group(1))); b, _ = await _get(ctx, u)
        if b is None: st['css_missing'] += 1; html = html.replace(tag, tag.replace(hm.group(1), u)); continue
        css = await fix_css(b.decode('utf-8', 'ignore'), u); st['css'] += 1
        html = html.replace(tag, '<style data-src="%s">%s</style>' % (u.replace('"', ''), css))
    # 2) url() inside existing <style> blocks and style="" attrs
    async def fix_style_blocks(h):
        parts, pos = [], 0
        for m in re.finditer(r'(<style\b[^>]*>)([\s\S]*?)(</style>)', h, re.I):
            if 'data-src=' in m.group(1): continue
            parts.append(h[pos:m.start()]); parts.append(m.group(1) + await fix_css(m.group(2), base) + m.group(3)); pos = m.end()
        parts.append(h[pos:]); return ''.join(parts)
    html = await fix_style_blocks(html)
    # 3) images: src / srcset first candidate / poster
    for m in list(re.finditer(r'<(img|source|video)\b[^>]*>', html, re.I)):
        tag = m.group(0); new = tag
        for attr in ('src', 'poster'):
            am = re.search(r'\b%s=["\']([^"\']+)["\']' % attr, new)
            if am and not am.group(1).startswith('data:'):
                u = urljoin(base, _h.unescape(am.group(1))); d = await data_uri(u)
                new = new.replace(am.group(0), '%s="%s"' % (attr, d or u))
        sm = re.search(r'\bsrcset=["\']([^"\']+)["\']', new)
        if sm:   # replace srcset by its first usable candidate as src when src missing/placeholder; drop srcset (avoids live refetch)
            first = sm.group(1).split(',')[0].strip().split(' ')[0]; u = urljoin(base, _h.unescape(first)); d = await data_uri(u)
            new = new.replace(sm.group(0), '')
            if d and ('src="' not in new or 'data:image/gif' in new or 'svg+xml;base64,PHN2Zy' in new[:200]):
                new = re.sub(r'\bsrc=["\'][^"\']*["\']', '', new, count=1).replace('<img', '<img src="%s"' % d, 1)
        new = re.sub(r'\bloading=["\']lazy["\']', '', new)
        if new != tag: html = html.replace(tag, new, 1)
    # 4) static snapshot: remove scripts, preloads; make relative links absolute through <base>
    html = re.sub(r'<script\b[\s\S]*?</script>', '', html, flags=re.I)
    html = re.sub(r'<link\b[^>]*rel=["\']?(?:preload|modulepreload|prefetch)["\']?[^>]*>', '', html, flags=re.I)
    if '<base ' not in html.lower(): html = re.sub(r'(<head\b[^>]*>)', r'\1<base href="%s">' % base.replace('"', ''), html, count=1, flags=re.I)
    (out / 'page.html').write_text(html, encoding='utf-8'); st['size'] = len(html)
    return st

async def verify_render(browser_ctx, out):
    """Open ONLY the saved page.html (file://, JS off, offline) and compare with page.png. Returns (ok, detail)."""
    from PIL import Image, ImageChops
    import io
    pg = await browser_ctx.new_page()
    try:
        await pg.route('**/*', lambda r: r.continue_() if r.request.url.startswith(('file:', 'data:')) else r.abort())
        await pg.set_viewport_size({'width': 1440, 'height': 900})
        await pg.goto((out / 'page.html').resolve().as_uri(), wait_until='load', timeout=30000); await pg.wait_for_timeout(600)
        png = await pg.screenshot(full_page=False)
    finally:
        await pg.close()
    a = Image.open(io.BytesIO(png)).convert('L').resize((96, 60))
    full = Image.open(out / 'page.png').convert('L'); w, h = full.size
    b = full.crop((0, 0, w, min(h, int(w * 900 / 1440)))).resize((96, 60))
    diff = sum(ImageChops.difference(a, b).getdata()) / (96 * 60 * 255)
    return diff < 0.18, 'diff %.3f' % diff
