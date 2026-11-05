"""Elite page extractor v2 (2026-11-03). Labels come only from elite_vocab.json.

One page -> outdir/
  page.png / page_mobile.png   full-page screenshots, 1440 and 390 wide
  page.html (+ iframe_source.html when the page is a wrapper)
  elements.jsonl   EVERY visible element: box, depth, parent, tag, key computed styles, own text,
                   chars/words, copy_role, ui_term, ml_class, family, layout
  blocks.json      meta + blocks (region/block/component nesting, surface, ordered copy with char counts) + families
  crops/           one PNG per block
  icons/ icons.json   inline SVG icons deduped by shape
  assets.json      images / background images / video / posters / fonts used (URL, size on page)
  motion.json      @keyframes, transitions, animated elements, motion libraries, GSAP tween count
  tokens.json      colours, fonts, type scale, radii, shadows, gaps actually used
  page.json        page record for the site ontology (url, title, headings, block sequence, family summary)

CLI:  python elite_extract.py URL OUTDIR        (library use: await extract(browser, url, outdir))
"""
import asyncio, hashlib, json, re, sys, collections
from pathlib import Path

JS = r"""
() => {
  const out = []; let n = 0;
  const pick = ['display','position','fontFamily','fontSize','fontWeight','lineHeight','letterSpacing',
    'textTransform','textAlign','color','backgroundColor','backgroundImage','borderTopWidth','borderTopColor',
    'borderTopStyle','borderRadius','boxShadow','paddingTop','paddingRight','paddingBottom','paddingLeft',
    'marginTop','marginBottom','gap','gridTemplateColumns','flexDirection','justifyContent','alignItems',
    'opacity','transform','transition','animationName','animationDuration','zIndex','overflow','objectFit',
    'backdropFilter','filter','mixBlendMode','cursor','fontVariantNumeric','whiteSpace'];
  const ownText = el => { let t=''; for (const c of el.childNodes) if (c.nodeType===3) t+=c.textContent; return t.replace(/\s+/g,' ').trim(); };
  const shape = el => [...el.children].slice(0,8).map(c=>c.tagName.toLowerCase()+'('+[...c.children].slice(0,6).map(g=>g.tagName.toLowerCase()).join(',')+')').join('');
  function walk(el, depth, parent){
    if (el.nodeType!==1) return;
    const tag = el.tagName.toLowerCase();
    if (['script','style','noscript','template','meta','link','head'].includes(tag)) return;
    const cs = getComputedStyle(el); if (cs.display==='none') return;
    const r = el.getBoundingClientRect();
    const visible = r.width>0 && r.height>0 && cs.visibility!=='hidden' && +cs.opacity>0.01;
    const id = n++;
    if (visible){
      const s={}; for (const k of pick) s[k]=cs[k];
      const rec = {id, parent, depth, tag, cls:(typeof el.className==='string'?el.className:'').slice(0,160),
        role: el.getAttribute('role')||'', aria: el.getAttribute('aria-label')||'',
        x: Math.round(r.left+scrollX), y: Math.round(r.top+scrollY), w: Math.round(r.width), h: Math.round(r.height),
        text: ownText(el).slice(0,4000), href: el.getAttribute('href')||'', src: el.currentSrc||el.getAttribute('src')||'',
        alt: el.getAttribute('alt')||'', type: el.getAttribute('type')||'', placeholder: el.getAttribute('placeholder')||'',
        children: el.children.length, shape: shape(el), style: s,
        selected: el.getAttribute('aria-selected')==='true'||el.getAttribute('aria-pressed')==='true'||/\b(active|selected|is-active|current)\b/.test(el.className&&el.className.baseVal===undefined?el.className:'')};
      if (tag==='svg'){ rec.svg = el.outerHTML.slice(0,20000); rec.svg_parts = el.querySelectorAll('path,circle,rect,line,polyline,polygon').length;
        rec.svg_circles = el.querySelectorAll('circle').length; rec.svg_rects = el.querySelectorAll('rect').length;
        rec.svg_poly = el.querySelectorAll('polyline,path').length; }
      if (tag==='pre'||tag==='code') rec.code = (el.innerText||'').slice(0,4000);
      out.push(rec);
    }
    if (tag==='svg') return;
    for (const c of el.children) walk(c, depth+1, id);
    if (el.shadowRoot) for (const c of el.shadowRoot.children) walk(c, depth+1, id);
  }
  walk(document.body, 0, -1);
  const keyframes=[], blocked=[];
  for (const sh of document.styleSheets){
    let rules; try { rules = sh.cssRules; } catch(e){ blocked.push(sh.href); continue; }
    const scan = rs => { for (const r of rs){ if (r.type===7) keyframes.push({name:r.name, css:r.cssText.slice(0,3000)}); else if (r.cssRules) scan(r.cssRules);} };
    try { scan(rules); } catch(e){}
  }
  const libs = {gsap: !!window.gsap, ScrollTrigger: !!window.ScrollTrigger,
    lottie: !!(window.lottie||window.bodymovin||document.querySelector('lottie-player,dotlottie-player,[data-animation-type=lottie]')),
    framer_motion: !!document.querySelector('[data-framer-appear-id],[data-framer-component-type]'),
    three: !!window.THREE, rive: !!window.rive||!!document.querySelector('canvas[class*=rive i]'),
    webflow_ix: !!document.querySelector('[data-w-id]'), swiper: !!document.querySelector('.swiper'),
    lenis: /lenis/.test(document.documentElement.className), aos: !!document.querySelector('[data-aos]'),
    spline: !!document.querySelector('spline-viewer,canvas[data-engine*=spline i]')};
  let gsapTweens = 0; try { gsapTweens = window.gsap ? gsap.globalTimeline.getChildren(true,true,false).length : 0; } catch(e){}
  const assets = [];
  for (const im of document.images) if (im.currentSrc) assets.push({kind:'img', url:im.currentSrc, w:im.naturalWidth, h:im.naturalHeight, alt:im.alt||''});
  for (const v of document.querySelectorAll('video')) { const u=v.currentSrc||v.src||(v.querySelector('source')||{}).src; if(u) assets.push({kind:'video', url:u, autoplay:v.autoplay, loop:v.loop, muted:v.muted}); if (v.poster) assets.push({kind:'poster', url:v.poster}); }
  for (const el of document.querySelectorAll('*')) { const b=getComputedStyle(el).backgroundImage; if (b && b.includes('url(')) for (const m of b.matchAll(/url\(["']?([^"')]+)["']?\)/g)) assets.push({kind:'bg', url:m[0].length?new URL(m[1],location.href).href:''}); }
  for (const e of performance.getEntriesByType('resource')) if (/\.(woff2?|ttf|otf)(\?|$)/i.test(e.name)) assets.push({kind:'font', url:e.name});
  for (const e of performance.getEntriesByType('resource')) if (/\.(json|lottie|riv|splinecode|glb|gltf)(\?|$)/i.test(e.name)) assets.push({kind:'motion_or_3d', url:e.name});
  const headings = [...document.querySelectorAll('h1,h2,h3')].slice(0,80).map(h=>({tag:h.tagName.toLowerCase(), text:(h.innerText||'').trim().slice(0,200)}));
  return {url: location.href, title: document.title, lang: document.documentElement.lang, height: document.documentElement.scrollHeight,
          description: (document.querySelector('meta[name=description]')||{}).content||'',
          elements: out, keyframes, blocked_sheets: blocked, libs, gsap_tweens: gsapTweens, assets, headings,
          scripts: [...document.scripts].map(s=>s.src).filter(Boolean)};
}
"""

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36'

def px(v):
    try: return float(str(v).replace('px', ''))
    except Exception: return 0.0

def clear(c): return (not c) or c in ('transparent', 'rgba(0, 0, 0, 0)')

def framed(e):
    s = e['style']
    return (not clear(s['backgroundColor']) or (px(s['borderTopWidth']) > 0 and s['borderTopStyle'] != 'none')
            or s['boxShadow'] != 'none' or s['backgroundImage'] not in ('none', ''))

NUM = re.compile(r'^[\s$£€¥+~<>≈−-]*\d[\d,.\s:]*\s*([%kKmMbBx×]|hrs?|hr/day|/day|/wk|/mo|ms|min|bpm|hz|kg|km|pts?)?\+?\s*$', re.I)
UNIT = re.compile(r'^(/\s*\d+|%|ms|s|h|min|hrs?|days?|kg|lbs?|bpm|hz|km|mi|pts?|k|m|x|/mo|/yr|/month|/year)$', re.I)
DELTA = re.compile(r'^[▲▼↑↓]?\s?[+−-]?\s?\d[\d.,]*\s*%?\s*(vs|from|since|this|last|wow|mom|yoy)\b|^[▲▼↑↓]\s?[+−-]?\d', re.I)
GLYPH = re.compile(r'^[^\w\s]{2,}$')

def is_button(e):
    s = e['style']
    return (e['tag'] == 'button' or e['role'] in ('button', 'tab') or e['type'] in ('submit', 'button')
            or (e['tag'] == 'a' and framed(e) and e['h'] <= 64 and e['w'] < 420))

def ui_term(e, kids, byid, childmap):
    tag, s, w, h = e['tag'], e['style'], e['w'], e['h']
    if tag == 'svg':
        if e.get('svg_circles', 0) >= 2 and w >= 50 and abs(w - h) < 12: return 'donut_ring_chart'
        if w <= 48 and h <= 48: return 'svg_icon'
        if e.get('svg_rects', 0) >= 4 and w > 100: return 'bar_chart'
        if e.get('svg_poly', 0) <= 3 and h <= 60 and w >= 60: return 'sparkline'
        return 'image'
    if tag == 'canvas': return 'canvas_render'
    if tag == 'video': return 'video_player'
    if tag == 'img':
        return 'avatar' if (abs(w - h) < 4 and w <= 120 and px(s['borderRadius']) >= w / 2 - 2) else 'image'
    if tag == 'table': return 'data_table'
    if tag in ('input', 'textarea', 'select'):
        return 'toggle_switch' if e['type'] == 'checkbox' and e['role'] == 'switch' else 'form_field'
    if e['role'] == 'tablist': return 'tab_bar'
    kidbtn = [c for c in childmap.get(e['id'], []) if is_button(c)]
    if len(kidbtn) >= 3 and len(kidbtn) == len(childmap.get(e['id'], [])) and max(c['h'] for c in kidbtn) < 52 \
            and len({c['y'] for c in kidbtn}) == 1 and all(len(c.get('alltext', '')) <= 20 for c in kidbtn):
        return 'segmented_control'
    if is_button(e): return 'pill_button' if px(s['borderRadius']) >= h / 2 - 1 else 'button'
    if tag == 'a': return 'text_link'
    if tag == 'hr' or (h <= 2 and w > 40 and not clear(s['backgroundColor'])): return 'divider_rule'
    if h <= 14 and w <= 14 and abs(w - h) <= 1 and px(s['borderRadius']) >= w / 2 - 1 and not clear(s['backgroundColor']): return 'status_dot'
    if 3 <= h <= 14 and w > 40 and not clear(s['backgroundColor']): return 'progress_bar'
    if tag == 'nav' or e['role'] == 'navigation': return 'navigation'
    if tag == 'header': return 'site_header'
    if tag == 'footer': return 'site_footer'
    if tag in ('ul', 'ol'): return 'list'
    if tag == 'li': return 'list_item'
    if tag == 'details' or e['role'] == 'region' and 'accordion' in e['cls'].lower(): return 'accordion_item'
    txt = e.get('textkids', [])
    if 2 <= len(txt) <= 3 and h <= 40 and w >= 80 and any(NUM.match(t['text']) for t in txt) and len({t['y'] // 6 for t in txt}) == 1:
        return 'metric_row'
    if framed(e) and h > 24:
        if h < 40 and w < 240 and px(s['borderRadius']) >= h / 2 - 1 and len(e.get('alltext', '')) <= 24: return 'badge_chip'
        if (e.get('position') == 'absolute' or s['position'] == 'absolute') and w < 320 and s['boxShadow'] != 'none': return 'tooltip_callout'
        if any(t['copy_hint'] == 'big_number' for t in txt) and w < 700: return 'stat_tile'
        if w < 1100 and kids >= 1: return 'card_panel'
    if e['text']: return 'glyph_graphic' if GLYPH.match(e['text']) else 'text'
    return 'layout_container'

def copy_role(e, scale, byid):
    t = e['text']; s = e['style']; fs = px(s['fontSize']); tag = e['tag']
    if not t: return ''
    if GLYPH.match(t): return 'glyph_graphic'
    if tag in ('pre', 'code') or e.get('in_code'): return 'code'
    if tag in ('label',) or e['placeholder']: return 'form_label'
    if e.get('in_seg'): return 'tab_label'
    if e.get('in_badge'): return 'badge_text'
    if e.get('in_button') or tag == 'button': return 'cta_label'
    if e.get('in_nav') and len(t) <= 30: return 'nav_label'
    if UNIT.match(t) and e.get('after_number'): return 'unit_suffix'
    if DELTA.match(t): return 'delta_indicator'
    if NUM.match(t):
        if fs >= max(24, scale['p90'] * 1.4): return 'stat_value'
        if e.get('in_metric_row'): return 'metric_value'
        if fs >= scale['p75'] + 4: return 'stat_value'
    if e.get('in_metric_row'): return 'metric_label'
    upper = s['textTransform'] == 'uppercase' or (t.upper() == t and any(c.isalpha() for c in t) and len(t) > 3)
    ls = px(s['letterSpacing']) if s['letterSpacing'] != 'normal' else 0
    if upper and fs <= scale['p50'] + 3 and (ls >= 0.1 or int(s['fontWeight'] or 400) >= 600):
        return 'panel_label' if e.get('in_card') else 'eyebrow_overline'
    if re.match(r'^0?\d{1,2}\.?$', t) and fs <= scale['p75']: return 'section_index_numeral'
    if tag == 'h1' or fs >= scale['max'] * 0.85 and fs >= 28: return 'display_headline'
    if tag == 'h2' or (fs >= scale['p90'] and fs >= 22): return 'section_headline'
    if tag == 'blockquote' or e.get('in_quote') or t[:1] in '“"«': return 'quote'
    if t[:1] in '—–' and len(t) < 80: return 'attribution'
    if tag in ('h3', 'h4', 'h5', 'h6') or (int(s['fontWeight'] or 400) >= 600 and len(t) < 70): return 'item_title'
    if tag == 'li' or e.get('in_li'): return 'list_item'
    if tag == 'a' or e.get('in_link'): return 'inline_link'
    if e.get('after_headline') and 40 <= len(t) <= 260 and fs > scale['p50']: return 'subheadline'
    if fs <= scale['p25'] and len(t) < 90: return 'meta_caption'
    if len(t) > 90: return 'body_paragraph'
    return 'supporting_text'

def layout(s):
    if s['display'] == 'grid' and s['gridTemplateColumns'] not in ('none', ''): return 'grid:%dcol' % len(s['gridTemplateColumns'].split())
    if 'flex' in s['display']: return 'flex-' + s['flexDirection']
    return s['display']

PAGE_RULES = [  # (page_type, url regex)  — first match wins; ontology pass refines with DOM cues
    ('pricing', r'/pricing|/plans'), ('comparison_vs', r'/vs[-/]|-vs-|/compare'), ('alternatives', r'alternative'),
    ('customer_story_detail', r'/(customers?|case-stud(y|ies)|stories)/[^/]+'), ('customer_story_index', r'/(customers?|case-stud(y|ies)|stories)/?$'),
    ('blog_post', r'/(blog|articles?|news|posts?)/[^/]+'), ('blog_index', r'/(blog|articles?|news)/?$'),
    ('docs_article', r'/docs?/[^/]+|/documentation/|/guides?/[^/]+'), ('docs_index', r'/docs?/?$'), ('api_reference', r'/api(-reference)?/'),
    ('changelog', r'changelog|release-notes|/updates?/?$|/whats-new'), ('demo_gallery', r'/demos?/?|/examples?/?$|/playground'),
    ('forum_thread', r'/(community|forums?)/.*(topic|thread|t)/'), ('forum_index', r'/(community|forums?)'),
    ('help_article', r'help\.|support\.|/help/|/hc/'), ('template_detail', r'/(templates?|showcase|gallery|inspiration)/[^/]+'),
    ('template_gallery', r'/(templates?|showcase|gallery|inspiration)/?$'), ('integration_detail', r'/(integrations?|apps|plugins|marketplace)/[^/]+'),
    ('integration_index', r'/(integrations?|apps|plugins|marketplace)/?$'), ('solution_by_industry', r'/(industr(y|ies)|sectors?)/'),
    ('solution_by_role', r'/(roles?|teams?|for|solutions?)/'), ('use_case_detail', r'/use-cases?/'), ('free_tool', r'/(tools?|free-|generator|calculator|converter)'),
    ('resource_detail', r'/(resources?|ebooks?|guides?|webinars?|reports?)/[^/]+'), ('resource_index', r'/(resources?|learn)/?$'),
    ('event_webinar', r'/(events?|webinars?)'), ('careers', r'/(careers?|jobs)'), ('about', r'/(about|company|team|mission)'),
    ('contact_sales', r'/(contact|demo|talk-to|book|sales)'), ('signup_login', r'/(sign-?up|log-?in|register|get-started|start)'),
    ('partner_program', r'/(partners?|affiliates?|agenc)'), ('legal', r'/(legal|terms|privacy|cookie|security)'),
    ('feature_detail', r'/(features?|product|platform)/[^/]+'), ('product_overview', r'/(features?|product|platform)/?$'),
]

def guess_page_type(url):
    from urllib.parse import urlparse
    u = urlparse(url); p = (u.path or '/').lower()
    if p in ('', '/') and not re.match(r'(help|support|docs|community)\.', u.netloc): return 'home'
    for t, rx in PAGE_RULES:
        if re.search(rx, u.netloc.lower() + p): return t
    return 'feature_detail' if p.count('/') <= 2 else 'unclassified'

# ------------------------------------------------------------------ analysis
def analyse(data, out):
    els = data['elements']; byid = {e['id']: e for e in els}
    childmap = collections.defaultdict(list)
    for e in els: childmap[e['parent']].append(e)
    # text descendants (bottom-up) and all text per element
    order = sorted(els, key=lambda e: -e['depth'])
    for e in order:
        tk = [e] if e['text'] else []
        for c in childmap.get(e['id'], []): tk += c.get('textkids_all', [])
        e['textkids_all'] = tk
        e['alltext'] = ' '.join(t['text'] for t in tk)[:400]
    sizes = sorted(px(e['style']['fontSize']) for e in els if e['text'])
    q = lambda f: sizes[min(len(sizes) - 1, int(len(sizes) * f))] if sizes else 16
    scale = {'p25': q(.25), 'p50': q(.5), 'p75': q(.75), 'p90': q(.9), 'max': sizes[-1] if sizes else 16}
    for e in els:
        e['copy_hint'] = 'big_number' if e['text'] and NUM.match(e['text']) and px(e['style']['fontSize']) >= max(22, scale['p90']) else ''
        e['textkids'] = e['textkids_all'][:4]
    kids = {e['id']: len(childmap.get(e['id'], [])) for e in els}
    for e in order[::-1]:  # top-down so ancestors are labelled first
        e['ui_term'] = ui_term(e, kids[e['id']], byid, childmap)
    # ancestry flags for copy roles
    prev_text = None
    for e in sorted(els, key=lambda e: e['id']):
        a = byid.get(e['parent'])
        while a:
            ut = a['ui_term']
            if ut in ('button', 'pill_button'): e['in_button'] = True
            if ut == 'segmented_control' or a['role'] == 'tablist': e['in_seg'] = True
            if ut == 'badge_chip': e['in_badge'] = True
            if ut == 'metric_row': e['in_metric_row'] = True
            if ut in ('card_panel', 'stat_tile', 'tooltip_callout') or a['tag'] in ('aside',): e['in_card'] = True
            if a['tag'] in ('nav', 'header'): e['in_nav'] = True
            if a['tag'] == 'li': e['in_li'] = True
            if a['tag'] == 'a': e['in_link'] = True
            if a['tag'] in ('blockquote', 'figure'): e['in_quote'] = True
            if a['tag'] in ('pre', 'code'): e['in_code'] = True
            a = byid.get(a['parent'])
        if e['text']:
            if prev_text is not None:
                e['after_number'] = bool(NUM.match(prev_text['text'])) and abs(prev_text['y'] - e['y']) < 60
                e['after_headline'] = prev_text['tag'] in ('h1', 'h2') or px(prev_text['style']['fontSize']) >= scale['p90']
            prev_text = e
    for e in els:
        e['copy_role'] = copy_role(e, scale, byid)
        e['chars'] = len(e['text']); e['words'] = len(e['text'].split()); e['layout'] = layout(e['style'])
    vocab_ml = json.loads((Path(__file__).with_name('elite_vocab.json')).read_text(encoding='utf-8'))['ml_class_map'] \
        if Path(__file__).with_name('elite_vocab.json').exists() else {}
    for e in els: e['ml_class'] = vocab_ml.get(e['ui_term'], 'Container')
    # families: same parent, same structural shape, >=2 members (widths may differ: bento cards)
    fam = collections.defaultdict(list)
    for e in els:
        if e['w'] > 30 and e['h'] > 16 and (e['children'] or e['text']):
            fam[(e['parent'], e['tag'], e['shape'])].append(e)
    families = []
    for (par, tag, shp), m in fam.items():
        if len(m) >= 2 and shp:
            fid = 'F%03d' % len(families)
            for x in m: x['family'] = fid
            terms = collections.Counter(x['ui_term'] for x in m).most_common(1)[0][0]
            families.append({'family_id': fid, 'count': len(m), 'ui_term': terms, 'tag': tag, 'shape': shp[:200],
                             'w_range': [min(x['w'] for x in m), max(x['w'] for x in m)], 'h_range': [min(x['h'] for x in m), max(x['h'] for x in m)],
                             'member_ids': [x['id'] for x in m],
                             'copy_slots': collections.Counter(t['copy_role'] for x in m for t in x['textkids_all']).most_common(),
                             'chars_per_member': [sum(t['chars'] for t in x['textkids_all']) for x in m]})
    # blocks
    blocks = []
    for e in els:
        sem = e['tag'] in ('header', 'nav', 'footer', 'section', 'aside', 'article', 'main', 'form', 'blockquote', 'table')
        media = e['ui_term'] in ('image', 'video_player', 'canvas_render', 'donut_ring_chart', 'bar_chart')
        if e['w'] >= 120 and e['h'] >= 32 and (sem or e['ui_term'] in ('card_panel', 'stat_tile', 'segmented_control', 'metric_row', 'data_table', 'tooltip_callout')
                                               or e.get('family') or (media and e['w'] >= 300)):
            tk = e['textkids_all']
            if not tk and not media and not any(c['ui_term'] in ('image', 'svg_icon', 'canvas_render', 'video_player') for c in childmap.get(e['id'], [])): continue
            s = e['style']
            blocks.append({'block_id': 'B%04d' % len(blocks), 'el': e['id'], 'tag': e['tag'], 'ui_term': e['ui_term'], 'ml_class': e['ml_class'],
                           'family': e.get('family', ''), 'x': e['x'], 'y': e['y'], 'w': e['w'], 'h': e['h'], 'layout': e['layout'],
                           'surface': {'bg': s['backgroundColor'], 'bg_image': s['backgroundImage'][:200], 'border': s['borderTopWidth'] + ' ' + s['borderTopStyle'] + ' ' + s['borderTopColor'],
                                       'radius': s['borderRadius'], 'shadow': s['boxShadow'], 'backdrop': s['backdropFilter'],
                                       'padding': ' '.join(s[k] for k in ('paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft')), 'gap': s['gap']},
                           'copy': [{'el': t['id'], 'role': t['copy_role'], 'text': t['text'], 'chars': t['chars'], 'words': t['words'],
                                     'type': '%s %s/%s ls %s %s' % (t['style']['fontWeight'], t['style']['fontSize'], t['style']['lineHeight'], t['style']['letterSpacing'], t['style']['fontFamily'].split(',')[0].strip('"\'')),
                                     'color': t['style']['color']} for t in sorted(tk, key=lambda t: t['id'])][:300],
                           'chars_total': sum(t['chars'] for t in tk),
                           'icons': sum(1 for c in els if c['ui_term'] == 'svg_icon' and e['x'] <= c['x'] < e['x'] + e['w'] and e['y'] <= c['y'] < e['y'] + e['h'])})
    ids = {bl['el']: bl for bl in blocks}
    for bl in blocks:
        a, d = byid[bl['el']]['parent'], 0
        while a in byid:
            if a in ids:
                bl.setdefault('parent_block', ids[a]['block_id']); d += 1
            a = byid[a]['parent']
        bl['level'] = ['region', 'block', 'component', 'sub_component'][min(d, 3)]
    for e in els:
        for k in ('textkids_all', 'textkids', 'alltext', 'copy_hint'): e.pop(k, None)
    return els, blocks, families, scale

async def extract(browser, url, outdir, mobile=True, interact=True):
    out = Path(outdir); (out / 'crops').mkdir(parents=True, exist_ok=True); (out / 'icons').mkdir(exist_ok=True)
    import time as _tm, sys as _sys; _t0 = _tm.time()
    def _t(stage): print('  [stage %.0fs] %s %s' % (_tm.time() - _t0, stage, url), file=_sys.stderr, flush=True)
    ctx = await browser.new_context(viewport={'width': 1440, 'height': 900}, user_agent=UA, locale='en-US')
    pg = await ctx.new_page()
    _t('goto')
    resp = await pg.goto(url, wait_until='domcontentloaded', timeout=60000)
    status = resp.status if resp else 0
    for _ in range(8):                               # bot checks (Vercel checkpoint, Cloudflare, Akamai) often clear themselves
        t = await pg.title()
        if not any(k in t for k in ('Checkpoint', 'Verification', 'Just a moment', 'Access Denied', 'Attention Required')): break
        await pg.wait_for_timeout(4000)
    _t('idle')
    try: await pg.wait_for_load_state('networkidle', timeout=12000)
    except Exception: pass
    await pg.evaluate("""()=>{for(const el of document.querySelectorAll('[id*=cookie i],[class*=cookie i],[id*=consent i],[class*=consent i],#onetrust-banner-sdk,.intercom-lightweight-app,#hubspot-messages-iframe-container'))
        if(getComputedStyle(el).position==='fixed'||getComputedStyle(el).position==='sticky') el.remove();}""")
    _t('scroll')
    for _ in range(60):
        done = await pg.evaluate('()=>{window.scrollBy(0,800);return innerHeight+scrollY>=document.documentElement.scrollHeight-5}')
        await pg.wait_for_timeout(220)
        if done: break
    await pg.evaluate('()=>window.scrollTo(0,0)'); await pg.wait_for_timeout(1500)
    from elite_interact import clear_gates
    _t('gates')
    try: gates = await clear_gates(pg, out)
    except Exception as e: gates = [{'error': str(e)[:120]}]
    _t('dom')
    data = await pg.evaluate(JS)
    _t('dom done %d' % len(data['elements']))
    if len(data['elements']) < 40 and len(pg.frames) > 1:       # wrapper page -> biggest iframe
        best, best_n = None, 0
        for fr in pg.frames[1:]:
            try: c = await fr.evaluate('()=>document.querySelectorAll("*").length')
            except Exception: continue
            if c > best_n: best, best_n = fr, c
        if best is not None:
            html = await best.content(); (out / 'iframe_source.html').write_text(html, encoding='utf-8')
            await pg.set_content(html, wait_until='load'); await pg.wait_for_timeout(2500)
            data = await pg.evaluate(JS); data['url'] = url + '#iframe'
    _t('shot')
    await pg.screenshot(path=str(out / 'page.png'), full_page=True)
    (out / 'page.html').write_text(await pg.content(), encoding='utf-8')
    _t('interact')
    inter = flow = tool = None
    if interact and not data['url'].endswith('#iframe'):
        import copy as _copy
        from elite_interact import explore, walk_flow, exercise_tool
        try: flow = await asyncio.wait_for(walk_flow(pg, url, out, lambda d, o: analyse(_copy.deepcopy(d), o), JS), timeout=150)
        except Exception as e: flow = {'error': str(e)[:150]}
        try: tool = await asyncio.wait_for(exercise_tool(pg, url, out, lambda d, o: analyse(_copy.deepcopy(d), o), JS), timeout=240)
        except Exception as e: tool = {'error': str(e)[:150]}
        try: inter = await asyncio.wait_for(explore(pg, url, out, lambda d, o: analyse(_copy.deepcopy(d), o), JS), timeout=240)
        except Exception as e: inter = {'error': str(e)[:150]}
    if mobile and not data['url'].endswith('#iframe'):
        try:
            await pg.set_viewport_size({'width': 390, 'height': 844}); await pg.wait_for_timeout(1200)
            await pg.screenshot(path=str(out / 'page_mobile.png'), full_page=True)
        except Exception: pass
    _t('analyse')
    await ctx.close()

    els, blocks, families, scale = analyse(data, out)
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(out / 'page.png')
    for bl in blocks:
        if bl['w'] * bl['h'] < 3000: continue
        box = (max(0, bl['x']), max(0, bl['y']), min(im.width, bl['x'] + bl['w']), min(im.height, bl['y'] + bl['h']))
        if box[2] > box[0] + 4 and box[3] > box[1] + 4:
            im.crop(box).save(out / 'crops' / (bl['block_id'] + '.png')); bl['crop'] = 'crops/' + bl['block_id'] + '.png'
    icons = {}
    for e in els:
        if e['tag'] == 'svg' and e.get('svg'):
            if e['ui_term'] == 'svg_icon':
                h = hashlib.sha1(re.sub(r'\s(class|id|style|width|height)="[^"]*"', '', e['svg']).encode()).hexdigest()[:12]
                if h not in icons:
                    (out / 'icons' / (h + '.svg')).write_text(e['svg'], encoding='utf-8')
                    icons[h] = {'icon': h, 'w': e['w'], 'h': e['h'], 'color': e['style']['color'], 'aria': e['aria'], 'uses': []}
                icons[h]['uses'].append(e['id'])
            elif e['ui_term'] in ('donut_ring_chart', 'bar_chart', 'sparkline', 'image'):
                h = hashlib.sha1(e['svg'].encode()).hexdigest()[:12]
                (out / 'icons' / ('graphic_' + h + '.svg')).write_text(e['svg'], encoding='utf-8'); e['svg_file'] = 'icons/graphic_' + h + '.svg'
        e.pop('svg', None)
    C = collections.Counter
    tokens = {'colors_text': C(e['style']['color'] for e in els if e['text']).most_common(24),
              'colors_bg': C(e['style']['backgroundColor'] for e in els if not clear(e['style']['backgroundColor'])).most_common(24),
              'font_families': C(e['style']['fontFamily'].split(',')[0].strip('"\' ') for e in els if e['text']).most_common(10),
              'type_scale': [[list(k), v] for k, v in sorted(C((e['style']['fontSize'], e['style']['fontWeight'], e['style']['lineHeight'], e['style']['letterSpacing'], e['copy_role'])
                                                                   for e in els if e['text']).items(), key=lambda kv: -px(kv[0][0]))],
              'radii': C(e['style']['borderRadius'] for e in els if e['style']['borderRadius'] != '0px').most_common(15),
              'shadows': C(e['style']['boxShadow'] for e in els if e['style']['boxShadow'] != 'none').most_common(12),
              'gaps': C(e['style']['gap'] for e in els if e['style']['gap'] not in ('normal', '0px')).most_common(15),
              'scale_quantiles': scale}
    motion = {'libs': data['libs'], 'gsap_tweens': data['gsap_tweens'], 'keyframes': data['keyframes'], 'blocked_stylesheets': data['blocked_sheets'],
              'animated_elements': [{'el': e['id'], 'ui_term': e['ui_term'], 'animation': e['style']['animationName'], 'dur': e['style']['animationDuration']}
                                    for e in els if e['style']['animationName'] not in ('none', '')],
              'transitions': C(e['style']['transition'] for e in els if not re.match(r'^(all|none) 0s ease 0s$', e['style']['transition'] or 'none 0s ease 0s')).most_common(30),
              'scripts': data['scripts']}
    seen, assets = set(), []
    for a in data['assets']:
        if a.get('url') and a['url'] not in seen and not a['url'].startswith('data:'): seen.add(a['url']); assets.append(a)
    with open(out / 'elements.jsonl', 'w', encoding='utf-8') as f:
        for e in els: f.write(json.dumps(e, ensure_ascii=False) + '\n')
    top_blocks = [b for b in blocks if b['level'] in ('region', 'block')]
    page = {'url': url, 'final_url': data['url'], 'http': status, 'title': data['title'], 'description': data['description'], 'lang': data['lang'],
            'page_type_guess': guess_page_type(data['url']), 'height': data['height'], 'headings': data['headings'],
            'counts': {'elements': len(els), 'text_elements': sum(1 for e in els if e['text']), 'chars': sum(e['chars'] for e in els),
                       'blocks': len(blocks), 'families': len(families), 'icons': len(icons), 'assets': len(assets),
                       'keyframes': len(data['keyframes'])},
            'block_sequence': [{'block_id': b['block_id'], 'ui_term': b['ui_term'], 'y': b['y'], 'h': b['h'], 'chars': b['chars_total'],
                                'first_text': next((c['text'] for c in b['copy'] if c['text']), '')[:80]} for b in top_blocks],
            'family_summary': [{k: f[k] for k in ('family_id', 'count', 'ui_term', 'w_range', 'h_range', 'copy_slots')} for f in families],
            'motion_libs': [k for k, v in data['libs'].items() if v], 'interactions': inter, 'flow': flow, 'tool': tool, 'gates': gates}
    for name, obj in [('blocks.json', {'blocks': blocks, 'families': families}), ('icons.json', list(icons.values())),
                      ('assets.json', assets), ('motion.json', motion), ('tokens.json', tokens), ('page.json', page)]:
        (out / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding='utf-8')
    return page

async def _main(url, outdir):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--disable-dev-shm-usage', '--no-sandbox'])
        page = await extract(b, url, outdir)
        await b.close()
    print(json.dumps({k: page[k] for k in ('url', 'title', 'page_type_guess', 'counts')}))

if __name__ == '__main__':
    asyncio.run(_main(sys.argv[1], sys.argv[2]))
