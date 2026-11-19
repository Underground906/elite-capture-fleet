import re, json
from pathlib import Path
from PIL import Image
APP_MODE = False
WALL = re.compile(r'access denied|just a moment|human|robot|verification|unable to process|forbidden|attention required|are you a|captcha|403|blocked', re.I)
COOKIE = re.compile(r'cookie|consent|we value your privacy|accept all|privacy preferences', re.I)
def qa(out):
    fails = []; png = out / 'page.png'
    if not png.exists(): return ['no screenshot saved']
    try:
        els = [json.loads(l) for l in open(out / 'elements.jsonl', encoding='utf-8')]
        pj = json.load(open(out / 'page.json', encoding='utf-8'))
    except Exception: return ['no element data']
    im = Image.open(png); w, h = im.size; docH = els[0]['h'] if els else h
    if h < docH * 0.9 and h < 16000: fails.append(f'screenshot cut short ({h}px of {docH}px)')
    words = sum(len((e.get('text') or '').split()) for e in els if e.get('tag') in ('p','h1','h2','h3','li','span','a','button'))
    if words < 120 and len(els) >= 80 and not APP_MODE: fails.append(f'little content ({words} words) - not worth keeping')
    if len(els) < 80: fails.append(f'thin page ({len(els)} elements) - wall or empty')
    t = pj.get('title') or ''
    if WALL.search(t): fails.append('bot wall / error page title: ' + t[:40])
    if (pj.get('http') or 200) >= 400: fails.append(f"http {pj.get('http')}")
    # cookie / consent box left on the page
    for e in els:
        st = e.get('style') or {}
        if st.get('position') in ('fixed', 'sticky') and e['w'] >= 300 and e['h'] >= 60 and COOKIE.search(e.get('text') or ''):
            fails.append('cookie/consent box still on page'); break
    try:
        from clean_live import blank_bands
        bb = blank_bands(png)
        if bb: fails.append('blank gap in page: %dpx at y=%d (content did not render)' % (bb[0][1], bb[0][0]))
    except Exception: pass
    # large images that did not render (flat blank area in screenshot)
    if h <= 40000:
        g = im.convert('L'); chk = flat = 0
        for e in els:
            if e.get('tag') != 'img' or e['w'] < 160 or e['h'] < 100 or e['x'] < 0 or e['y'] < 0 or e['x'] + 20 >= w or e['y'] + 20 >= h: continue
            if (e.get('src') or '').lower().endswith('.svg'): continue
            c = g.crop((e['x'], e['y'], min(w, e['x'] + e['w']), min(h, e['y'] + e['h']))).resize((24, 24)); px = list(c.getdata()); m = sum(px) / len(px)
            chk += 1
            if (sum((p - m) ** 2 for p in px) / len(px)) ** .5 < 4: flat += 1
        if chk >= 2 and flat / chk >= 0.3: fails.append(f'{flat} of {chk} large images blank (not rendered)')
    return fails

