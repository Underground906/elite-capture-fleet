"""Image -> measured, rebrandable spec (2026-11-04).

For every content image on a site's KEPT pages (illustrations, product shots, UI mockups, diagrams, hero art):
  1. measure it (native size, opaque bounding box, 8-colour palette with shares)
  2. ask the free NVIDIA vision model for a layered scene graph: outer shape, every card/shape/text/arrow,
     and SLOTS (product_shot / photo / icon / logo / avatar / screenshot) with pixel boxes, colours as token roles
  3. render the spec to SVG (cairosvg -> PNG) and score it against the original (windowed SSIM + edge IoU)
  4. if the score is low, one correction pass (original + render side by side)
Outputs per image in R2 ui-library-elite/_image_spec/<domain>/<id>/ : spec.json, render.svg, wire.svg (slots labelled),
source.png (<=512px reference), plus <domain>/INDEX.json. Swap spec['tokens'] for a brand file = rebrand.

  python elite_imagespec.py follow.it gsap.com ...     [--max 30]
"""
import base64, hashlib, io, json, math, re, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from xml.sax.saxutils import escape
import numpy as np
from PIL import Image
try: import pillow_avif  # noqa: F401
except Exception: pass

ROOT = Path(__file__).parent
R2 = 'r2:enterprise-canon/ui-library-elite'
OUT = R2 + '/_image_spec'
KEY = Path('/root/mmx/nvidia_key.txt').read_text().strip() if Path('/root/mmx/nvidia_key.txt').exists() else ''
URL = 'https://integrate.api.nvidia.com/v1/chat/completions'
MODEL = 'nvidia/nemotron-3.5-super-vl-120b-a12b'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36'}
SLOTS = ['product_shot_slot', 'photo_slot', 'screenshot_slot', 'icon_slot', 'logo_slot', 'avatar_slot', 'illustration_slot']
ROLES = ['background', 'card', 'panel', 'shape', 'text', 'button', 'badge', 'chip', 'input', 'chart', 'arrow', 'connector', 'divider'] + SLOTS
SHAPES = ['rect', 'ellipse', 'line', 'arrow', 'polygon', 'text']

def rc(*a, timeout=600): return subprocess.run(['rclone', *a], capture_output=True, text=True, timeout=timeout)

# ---------- measurement ----------
def measure(im):
    rgba = im.convert('RGBA'); a = np.asarray(rgba)[:, :, 3]
    ys, xs = np.where(a > 16)
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if len(xs) else [0, 0, im.width, im.height]
    rgb = Image.new('RGB', rgba.size, (255, 255, 255)); rgb.paste(rgba, mask=rgba.split()[3])
    q = rgb.copy(); q.thumbnail((200, 200)); q = q.quantize(8, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:24]; counts = sorted(q.getcolors(), reverse=True); tot = sum(c for c, _ in counts)
    palette = [{'hex': '#%02X%02X%02X' % tuple(pal[i * 3:i * 3 + 3]), 'share': round(c / tot, 3)} for c, i in counts]
    return {'native_w': im.width, 'native_h': im.height, 'opaque_bbox': bbox, 'transparent': bool((a < 250).mean() > 0.02),
            'aspect': round(im.width / im.height, 3), 'palette': palette}, rgb

# ---------- render ----------
def col(t, v, default='none'):
    if not v: return default
    return t.get(v, v) if isinstance(v, str) else default

def render(spec, wire=False):
    t = dict(spec.get('tokens', {})); W, H = spec['canvas']['w'], spec['canvas']['h']
    font = escape(t.get('font', 'Inter, sans-serif'))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           '<defs><marker id="ah" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker></defs>']
    bg = col(t, spec['canvas'].get('bg'), 'none')
    if bg not in ('none', 'transparent'): out.append(f'<rect width="{W}" height="{H}" fill="{bg}"/>')
    for L in sorted(spec.get('layers', []), key=lambda L: L.get('z', 0)):
        try:
            sh = L.get('shape', 'rect'); x, y, w, h = (float(L.get(k, 0) or 0) for k in ('x', 'y', 'w', 'h'))
            fill = col(t, L.get('fill')); stroke = col(t, L.get('stroke')); sw = L.get('stroke_width', 1.5 if stroke != 'none' else 0)
            op = L.get('opacity', 1); role = L.get('role', '')
            if wire and role in SLOTS: fill, stroke, sw = '#E9EEF5', '#5B7DB1', 2
            st = f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" opacity="{op}"' + (' stroke-dasharray="6 5"' if L.get('dashed') else '')
            if sh == 'rect': out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{L.get("radius", 0)}" {st}/>')
            elif sh == 'ellipse': out.append(f'<ellipse cx="{x + w / 2}" cy="{y + h / 2}" rx="{w / 2}" ry="{h / 2}" {st}/>')
            elif sh in ('line', 'arrow'):
                x2, y2 = L.get('x2', x + w), L.get('y2', y + h)
                out.append(f'<line x1="{x}" y1="{y}" x2="{x2}" y2="{y2}" stroke="{stroke if stroke != "none" else fill}" stroke-width="{sw or 2}"'
                           + (' stroke-dasharray="6 5"' if L.get('dashed') else '') + (' marker-end="url(#ah)"' if sh == 'arrow' else '') + '/>')
            elif sh == 'polygon' and L.get('points'):
                out.append(f'<polygon points="{" ".join(f"{a},{b}" for a, b in L["points"])}" {st}/>')
            elif sh == 'text':
                size = L.get('font_size', max(10, h * 0.8)); anchor = {'center': 'middle', 'right': 'end'}.get(L.get('align'), 'start')
                tx = x + (w / 2 if anchor == 'middle' else w if anchor == 'end' else 0)
                out.append(f'<text x="{tx}" y="{y + size * 0.85}" font-family="{font}" font-size="{size}" font-weight="{L.get("font_weight", 400)}" '
                           f'fill="{fill if fill != "none" else "#000"}" text-anchor="{anchor}" opacity="{op}">{escape(str(L.get("text", ""))[:120])}</text>')
            if wire and role in SLOTS:
                out.append(f'<line x1="{x}" y1="{y}" x2="{x + w}" y2="{y + h}" stroke="#5B7DB1" stroke-width="1"/><line x1="{x + w}" y1="{y}" x2="{x}" y2="{y + h}" stroke="#5B7DB1" stroke-width="1"/>')
                if w >= 70 and h >= 24:
                    out.append(f'<text x="{x + 6}" y="{y + 16}" font-family="Inter, sans-serif" font-size="12" fill="#23406E">{role.replace("_slot", "")} {int(w)}×{int(h)}</text>')
        except Exception:
            continue
    out.append('</svg>')
    return '\n'.join(out)

def raster(svg, W, H):
    import cairosvg
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=W, output_height=H, background_color='white')
    return Image.open(io.BytesIO(png)).convert('RGB')

# ---------- score ----------
def _box(a, k=7):
    c = np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1); r = k // 2
    H, W = a.shape; y0 = np.clip(np.arange(H) - r, 0, H); y1 = np.clip(np.arange(H) + r + 1, 0, H)
    x0 = np.clip(np.arange(W) - r, 0, W); x1 = np.clip(np.arange(W) + r + 1, 0, W)
    s = c[y1][:, x1] - c[y0][:, x1] - c[y1][:, x0] + c[y0][:, x0]
    return s / ((y1 - y0)[:, None] * (x1 - x0)[None, :])

def score(orig, rend):
    S = 256; a = orig.copy(); a.thumbnail((S, S)); b = rend.resize(a.size)
    A = np.asarray(a.convert('L'), dtype=float); B = np.asarray(b.convert('L'), dtype=float)
    ma, mb = _box(A), _box(B); va = _box(A * A) - ma ** 2; vb = _box(B * B) - mb ** 2; cov = _box(A * B) - ma * mb
    C1, C2 = 6.5, 58.5
    ssim = float((((2 * ma * mb + C1) * (2 * cov + C2)) / ((ma ** 2 + mb ** 2 + C1) * (va + vb + C2))).mean())
    def edges(X):
        g = np.hypot(np.diff(X, axis=1, prepend=X[:, :1]), np.diff(X, axis=0, prepend=X[:1]))
        e = g > max(12, np.percentile(g, 85)); d = e.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1): d |= np.roll(np.roll(e, dy, 0), dx, 1)
        return e, d
    ea, da = edges(A); eb, db = edges(B)
    prec = (eb & da).sum() / max(1, eb.sum()); rec = (ea & db).sum() / max(1, ea.sum())
    eiou = float(2 * prec * rec / max(1e-6, prec + rec))
    ca = np.asarray(a.resize((16, 16)), dtype=float); cb = np.asarray(b.resize((16, 16)), dtype=float)
    colour = float(1 - np.abs(ca - cb).mean() / 255)
    return {'ssim': round(ssim, 3), 'edge_f1': round(eiou, 3), 'colour': round(colour, 3),
            'overall': round(0.45 * ssim + 0.35 * eiou + 0.2 * colour, 3)}

# ---------- model ----------
PROMPT = """You are a senior visual designer reverse-engineering an image into a measured, rebuildable spec so it can be redrawn in Figma/React with another brand's colours, icons and product shots.
Image: {w}x{h}px (coordinates below are in THIS pixel space). Alt text: "{alt}". Page: {page}.
Measured palette (hex, share of pixels): {palette}. Opaque bounding box: {bbox}.

Return ONLY JSON:
{{"composition": {{"pattern": "snake_case name of the layout pattern (e.g. floating_ui_cards_collage, device_mockup_with_overlay_cards, hub_and_spoke_diagram, product_shot_on_gradient, step_flow_with_arrows, isometric_illustration, bar_chart_card)",
                  "design_name": "the name designers use for this kind of visual",
                  "purpose": "what this image communicates on the page", "use_cases": ["3 places it would fit"],
                  "techniques": ["visual techniques: shadows, glow, glassmorphism, dashed connectors, tilt, overlap, gradient mesh ..."]}},
 "canvas": {{"w": {w}, "h": {h}, "bg": "token role or 'transparent'"}},
 "tokens": {{"role_name": "#HEX", ... (6-12 roles e.g. bg, card_fill, card_stroke, accent, accent_2, text_primary, text_muted, slot_fill; take hexes from the measured palette), "font": "closest font family"}},
 "layers": [{{"id": "L1", "role": one of {roles}, "shape": one of {shapes},
             "x": int, "y": int, "w": int, "h": int, "radius": int, "fill": "token role", "stroke": "token role or null", "stroke_width": number,
             "dashed": bool, "opacity": number, "z": int, "text": "only for text layers", "font_size": int, "font_weight": int, "align": "left|center|right",
             "x2": int, "y2": int, "points": [[x,y],...], "parent": "id of the card/panel it sits in or null", "label": "what it is, e.g. 'stat card', 'phone screen', 'brand logo'"}}]}}
Rules: list EVERY visible card, panel, shape, text line, arrow/connector and divider with accurate pixel boxes (measure carefully against the {w}x{h} grid).
Anything that is a photo, product, screenshot, logo, avatar, icon or complex illustration becomes a *_slot layer (a box to drop the replacement asset into) with its exact box and its average colour as fill.
Order layers back to front (z). 8-60 layers."""

REFINE = """Left = original image, right = your previous spec rendered. Score {score}. Fix positions/sizes/colours/missing layers so the render matches the original's shapes and layout. Return the FULL corrected JSON in the same format. Previous spec:
{spec}"""

def call(content, max_tokens=8000):
    body = {'model': MODEL, 'temperature': 0.1, 'max_tokens': max_tokens, 'chat_template_kwargs': {'enable_thinking': False},
            'messages': [{'role': 'system', 'content': '/no_think'}, {'role': 'user', 'content': content}]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=240) as r:
        msg = json.loads(r.read())['choices'][0]['message']
    txt = msg.get('content') or msg.get('reasoning_content') or ''
    txt = re.sub(r'^```(json)?|```$', '', txt.strip(), flags=re.M)
    return json.JSONDecoder().raw_decode(txt[txt.index('{'):])[0]

def b64(im, fmt='JPEG'):
    buf = io.BytesIO(); im.save(buf, fmt, quality=85); return base64.b64encode(buf.getvalue()).decode()

def img_part(im): return {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64(im)}}

def spec_image(url, alt, page):
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
    im = Image.open(io.BytesIO(raw)); im.load()
    m, rgb = measure(im)
    work = rgb.copy(); work.thumbnail((1024, 1024)); w, h = work.size
    sc = w / rgb.width
    pal = ', '.join(f"{p['hex']} {p['share']}" for p in m['palette'])
    bbox = [int(v * sc) for v in m['opaque_bbox']]
    p = PROMPT.format(w=w, h=h, alt=alt[:120], page=page, palette=pal, bbox=bbox, roles=ROLES, shapes=SHAPES)
    spec = call([{'type': 'text', 'text': p}, img_part(work)])
    spec['canvas'] = {'w': w, 'h': h, 'bg': (spec.get('canvas') or {}).get('bg', 'transparent')}
    r1 = raster(render(spec), w, h); s1 = score(work, r1); best, bs, passes = spec, s1, 1
    if s1['overall'] < 0.72:
        pair = Image.new('RGB', (w * 2 + 20, h), 'white'); pair.paste(work, (0, 0)); pair.paste(r1, (w + 20, 0))
        if pair.width > 2048: pair.thumbnail((2048, 2048))
        try:
            s2spec = call([{'type': 'text', 'text': REFINE.format(score=s1, spec=json.dumps(spec)[:12000])}, img_part(pair)])
            s2spec['canvas'] = spec['canvas']; s2 = score(work, raster(render(s2spec), w, h)); passes = 2
            if s2['overall'] > s1['overall']: best, bs = s2spec, s2
        except Exception:
            pass
    best.update(id=hashlib.md5(url.encode()).hexdigest()[:12], source_url=url, alt=alt, page=page, measured=m,
                scale_to_native=round(1 / sc, 4), score=bs, passes=passes, model=MODEL, made_at=time.strftime('%Y-%m-%d %H:%M:%S'),
                slots=[{k: L.get(k) for k in ('id', 'role', 'x', 'y', 'w', 'h', 'label')} for L in best.get('layers', []) if L.get('role') in SLOTS])
    return best, work

def stem(u): return re.sub(r'@\d+w(?=\.)|[-_]\d{2,4}x\d{2,4}(?=\.)', '', u.split('?')[0])

def site(domain, cap=30):
    runs = rc('cat', f'{R2}/{domain}/', '--include', 'run*.jsonl', '--max-depth', '1').stdout.splitlines()
    dirs = []
    for l in runs:
        try: r = json.loads(l)
        except Exception: continue
        if r.get('status') == 'ok' and (r.get('http') or 200) < 400 and r['dir'] not in dirs: dirs.append(r['dir'])
    idx_path = Path(f'/root/elite/.imagespec_{domain}.json')
    index = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    cand = {}
    for d in dirs:
        a = rc('cat', f'{R2}/{domain}/pages/{d}/assets.json').stdout
        try: assets = json.loads(a)
        except Exception: continue
        for x in assets:
            u = x.get('url', '')
            if x.get('kind') != 'img' or not u.startswith('http') or re.search(r'\.(svg|gif)(\?|$)|data:', u, re.I): continue
            if (x.get('w') or 0) < 160 or (x.get('h') or 0) < 120: continue
            k = stem(u)
            if k not in cand or (x.get('w', 0) * x.get('h', 0)) > cand[k][1]: cand[k] = (x, x.get('w', 0) * x.get('h', 0), d)
    todo = sorted(cand.values(), key=lambda c: -c[1])[:cap]
    print(domain, 'pages', len(dirs), 'candidate images', len(cand), 'doing', len(todo), flush=True)
    for x, _, d in todo:
        u = x['url']; key = hashlib.md5(u.encode()).hexdigest()[:12]
        if key in index and 'error' not in index[key]: continue
        try:
            spec, work = spec_image(u, x.get('alt') or '', d)
            tmp = Path(tempfile.mkdtemp())
            (tmp / 'spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding='utf-8')
            (tmp / 'render.svg').write_text(render(spec), encoding='utf-8')
            (tmp / 'wire.svg').write_text(render(spec, wire=True), encoding='utf-8')
            ref = work.copy(); ref.thumbnail((512, 512)); ref.save(tmp / 'source.png')
            rc('copy', str(tmp), f'{OUT}/{domain}/{key}/')
            index[key] = {'url': u, 'page': d, 'pattern': spec.get('composition', {}).get('pattern'), 'score': spec['score'],
                          'native': [spec['measured']['native_w'], spec['measured']['native_h']], 'slots': len(spec['slots']), 'layers': len(spec.get('layers', []))}
            print(domain, key, spec['score'], index[key]['pattern'], 'slots', len(spec['slots']), flush=True)
        except Exception as e:
            index[key] = {'url': u, 'page': d, 'error': str(e)[:200]}
            print(domain, key, 'ERR', str(e)[:150], flush=True)
        idx_path.write_text(json.dumps(index, indent=1))
        time.sleep(3)
    ip = Path(tempfile.mkdtemp()) / 'INDEX.json'; ip.write_text(json.dumps(index, indent=1))
    rc('copyto', str(ip), f'{OUT}/{domain}/INDEX.json')

if __name__ == '__main__':
    a = sys.argv[1:]
    cap = int(a[a.index('--max') + 1]) if '--max' in a else 30
    for d in [x for x in a if '.' in x and not x.isdigit()]: site(d, cap)
