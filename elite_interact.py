"""Interactions + flows for the elite capture (2026-11-03).

Terms (John's, 29 Oct): interaction = a click that changes a box or the page; screen = a new layout;
capability = a whole task flow made of screens.

explore(pg, url, out, analyse)  -> interactions.json + interactions/iNN.png
  Finds every clickable trigger that is not a plain link away (buttons, tabs, aria-expanded/haspopup,
  carousel arrows, gallery thumbs, photo tiles, accordions, menus, play buttons), clicks each once,
  classifies the effect (modal_or_lightbox, drawer, popover_or_menu, disclosure, tab_switch,
  carousel_advance, media_play, content_change, navigation, screen_change) and records a viewport
  screenshot + the newly visible elements (labelled with the same ledger as the page).
walk_flow(pg, url, out, analyse) -> flow.json + flow/sNN.png
  For wizard / multi-step pages: chooses an option in each choice group, fills number fields only,
  clicks Next/Continue, records every screen. NEVER clicks submit/send/pay/buy/sign-up/request/book and
  never types names, emails or phone numbers.
"""
import json, re

SAFE_NEXT = re.compile(r"^\s*(next|continue|get started|start|let'?s go|skip|ok|okay|done|see (results|options|rates)|show (results|more)|→|›|>)\s*[→›>]?\s*$", re.I)
FORBID = re.compile(r"(buy|add to (cart|bag|basket)|checkout|check out|pay|purchase|order|subscribe|sign ?up|register|submit|send|request|apply|book|schedule|call|contact|delete|remove|log ?out|sign ?out|tour|download|install|share|report|unfollow|follow|favorite|save search|donate|join|claim|accept|agree)", re.I)

ENUM = r"""
(maxN) => {
  const FORBID = /(buy|add to (cart|bag|basket)|checkout|check out|pay|purchase|order|subscribe|sign ?up|register|submit|send|request|apply|book|schedule|call|contact|delete|remove|log ?out|sign ?out|tour|download|install|share|report|follow|favorite|save search|donate|join|claim|accept|agree)/i;
  const HINT = /(carousel|slider|slide|swiper|next|prev|arrow|gallery|photo|thumb|tab|accordion|toggle|menu|dropdown|modal|play|expand|more|filter|sort|street|map|tour|video|lightbox|zoom|popover|tooltip|chip|segment)/i;
  const cssPath = el => { const p=[]; while (el && el.nodeType===1 && el!==document.body){ let i=1,s=el; while((s=s.previousElementSibling)) if (s.tagName===el.tagName) i++; p.unshift(el.tagName.toLowerCase()+':nth-of-type('+i+')'); el=el.parentElement;} return 'body > '+p.join(' > '); };
  const cands = [], seen = new Set();
  for (const el of document.querySelectorAll('button,[role=button],[role=tab],[aria-expanded],[aria-haspopup],[aria-controls],summary,a[href^="#"],[class*=carousel i] *,[class*=gallery i] img,[class*=photo i],[data-rf-test-id],[class*=thumb i],[class*=arrow i],[class*=next i],[class*=prev i]')){
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (r.width<8||r.height<8||cs.visibility==='hidden'||cs.display==='none'||+cs.opacity<0.05) continue;
    if (el.closest('header nav a[href]:not([href^="#"])')) continue;
    if (el.tagName==='A' && el.getAttribute('href') && !el.getAttribute('href').startsWith('#')) continue;
    const label = ((el.innerText||'')+' '+(el.getAttribute('aria-label')||'')+' '+(el.getAttribute('title')||'')).replace(/\s+/g,' ').trim().slice(0,80);
    if (FORBID.test(label)) continue;
    if (el.type==='submit') continue;
    const iconSig = (el.querySelector('svg path')||{getAttribute:()=>''}).getAttribute('d')||'';
    const sig = el.tagName+'|'+(el.getAttribute('role')||'')+'|'+(el.className&&el.className.baseVal===undefined?String(el.className).split(' ').slice(0,2).join('.'):'')+'|'+(label.length<20?label:'')
              +'|'+(el.getAttribute('title')||el.getAttribute('data-testid')||el.getAttribute('aria-label')||'')+'|'+iconSig.slice(0,40)
              +(label ? '' : '|'+Math.round((r.left+scrollX)/30)+','+Math.round((r.top+scrollY)/30));
    if (seen.has(sig)) continue; seen.add(sig);
    const score = (el.getAttribute('aria-expanded')!==null||el.getAttribute('aria-haspopup')?3:0)+(el.getAttribute('role')==='tab'?2:0)+(HINT.test(String(el.className)+' '+label+' '+(el.getAttribute('data-rf-test-id')||''))?2:0)+(el.tagName==='BUTTON'?1:0);
    cands.push({path: cssPath(el), label, tag: el.tagName.toLowerCase(), role: el.getAttribute('role')||'', expanded: el.getAttribute('aria-expanded'),
                haspopup: el.getAttribute('aria-haspopup')||'', cls: String(el.className&&el.className.baseVal===undefined?el.className:'').slice(0,100),
                x: Math.round(r.left+scrollX), y: Math.round(r.top+scrollY), w: Math.round(r.width), h: Math.round(r.height), score});
  }
  cands.sort((a,b)=>b.score-a.score || a.y-b.y);
  return cands.slice(0, maxN);
}
"""

STATE = r"""
(path) => {
  const vis = el => { const r=el.getBoundingClientRect(), cs=getComputedStyle(el); return r.width>0&&r.height>0&&cs.visibility!=='hidden'&&cs.display!=='none'&&+cs.opacity>0.05; };
  const dialogs = [...document.querySelectorAll('[role=dialog],[aria-modal=true],dialog[open],[class*=modal i],[class*=lightbox i],[class*=drawer i],[class*=popover i],[role=menu],[role=listbox]')].filter(vis)
     .map(d=>{const r=d.getBoundingClientRect(); return {tag:d.tagName.toLowerCase(), role:d.getAttribute('role')||'', cls:String(d.className&&d.className.baseVal===undefined?d.className:'').slice(0,80), x:r.left,y:r.top,w:r.width,h:r.height};});
  const fixedBig = [...document.querySelectorAll('body *')].filter(e=>{const cs=getComputedStyle(e); if(cs.position!=='fixed') return false; const r=e.getBoundingClientRect(); return r.width*r.height>innerWidth*innerHeight*0.35 && vis(e);}).length;
  let t = document.querySelector(path);
  return {url: location.href, dialogs, fixedBig, text: (document.body.innerText||'').length, nodes: document.querySelectorAll('body *').length,
          expanded: t ? t.getAttribute('aria-expanded') : null, selected: t ? t.getAttribute('aria-selected') : null,
          videosPlaying: [...document.querySelectorAll('video')].filter(v=>!v.paused).length, scrollY};
}
"""

def _effect(c, b, a):
    if a['url'].split('#')[0] != b['url'].split('#')[0]: return 'navigation'
    if len(a['dialogs']) > len(b['dialogs']) or a['fixedBig'] > b['fixedBig']:
        d = (a['dialogs'] or [{}])[-1]
        cls = (d.get('cls', '') + d.get('role', '')).lower()
        if 'lightbox' in cls or 'gallery' in cls or 'photo' in cls or a['fixedBig'] > b['fixedBig']: return 'modal_or_lightbox'
        if 'drawer' in cls or (d.get('h', 0) > 500 and d.get('w', 9999) < 600): return 'drawer'
        if 'menu' in cls or 'listbox' in cls or 'popover' in cls or d.get('w', 0) < 500: return 'popover_or_menu'
        return 'modal_or_lightbox'
    if c['expanded'] is not None and a['expanded'] != b['expanded']: return 'disclosure'
    if c['role'] == 'tab' or a['selected'] != b['selected']: return 'tab_switch'
    if a['videosPlaying'] > b['videosPlaying']: return 'media_play'
    if re.search(r'carousel|slider|swiper|next|prev|arrow|gallery|thumb', c['cls'] + c['label'], re.I) and abs(a['nodes'] - b['nodes']) < 40: return 'carousel_advance'
    if a['url'] != b['url']: return 'hash_change'
    if abs(a['nodes'] - b['nodes']) > 3 or abs(a['text'] - b['text']) > 20: return 'content_change'
    return ''

async def _ledger_keys(pg, JS):
    d = await pg.evaluate(JS)
    return d, {(e['tag'], e['text'][:60], e['x'] // 4, e['y'] // 4) for e in d['elements']}

async def explore(pg, url, out, analyse, JS, max_n=40, reload_url=True):
    (out / 'interactions').mkdir(exist_ok=True)
    base_data, base_keys = await _ledger_keys(pg, JS)
    cands = await pg.evaluate(ENUM, max_n)
    rec = []
    for i, c in enumerate(cands):
        try:
            b = await pg.evaluate(STATE, c['path'])
            loc = pg.locator(c['path']).first
            await loc.scroll_into_view_if_needed(timeout=3000)
            b = await pg.evaluate(STATE, c['path'])
            await loc.click(timeout=3000, no_wait_after=True)
            await pg.wait_for_timeout(1300)
            a = await pg.evaluate(STATE, c['path'])
            eff = _effect(c, b, a)
            item = {'i': i, 'trigger': c, 'effect': eff, 'url_after': a['url'], 'dialogs': a['dialogs']}
            if eff:
                shot = 'interactions/i%02d.png' % i
                await pg.screenshot(path=str(out / shot)); item['screenshot'] = shot
                if eff != 'navigation':
                    d2, k2 = await _ledger_keys(pg, JS)
                    new = [e for e in d2['elements'] if (e['tag'], e['text'][:60], e['x'] // 4, e['y'] // 4) not in base_keys]
                    if new:
                        d2['elements'] = new
                        els, blocks, fams, _ = analyse(d2, out)
                        item['new_elements'] = len(els)
                        item['new_copy'] = [{'role': e['copy_role'], 'text': e['text'][:300], 'chars': e['chars'], 'ui_term': e['ui_term']} for e in els if e['text']][:120]
                        item['new_components'] = sorted({e['ui_term'] for e in els} - {'text', 'layout_container'})
                        item['new_families'] = [{k: f[k] for k in ('ui_term', 'count', 'copy_slots')} for f in fams]
                        item['images_shown'] = [e['src'] for e in els if e['tag'] == 'img' and e['src']][:30]
            rec.append(item)
            # restore
            if eff in ('modal_or_lightbox', 'drawer', 'popover_or_menu'):
                await pg.keyboard.press('Escape'); await pg.wait_for_timeout(500)
                s = await pg.evaluate(STATE, c['path'])
                if (len(s['dialogs']) > len(b['dialogs']) or s['fixedBig'] > b['fixedBig']) and reload_url:
                    await pg.goto(url, wait_until='domcontentloaded', timeout=45000); await pg.wait_for_timeout(2500)
            elif eff in ('navigation', 'hash_change') or a['url'] != b['url']:
                await pg.goto(url, wait_until='domcontentloaded', timeout=45000); await pg.wait_for_timeout(2500)
        except Exception as e:
            rec.append({'i': i, 'trigger': c, 'error': str(e)[:160]})
            try:
                if pg.url.split('#')[0] != url.split('#')[0]:
                    await pg.goto(url, wait_until='domcontentloaded', timeout=45000); await pg.wait_for_timeout(2000)
            except Exception: pass
    summary = {'candidates': len(cands), 'with_effect': sum(1 for r in rec if r.get('effect')),
               'effects': {k: sum(1 for r in rec if r.get('effect') == k) for k in sorted({r.get('effect') for r in rec if r.get('effect')})}}
    (out / 'interactions.json').write_text(json.dumps({'summary': summary, 'interactions': rec}, ensure_ascii=False, indent=1), encoding='utf-8')
    return summary

FLOW_HINT = re.compile(r'(pre-?approv|prequal|get-?started|onboard|quiz|quote|estimate|calculator|wizard|signup|create|setup|survey|questionnaire|find-?your|match)', re.I)

STEP = r"""
() => {
  const vis = el => { const r=el.getBoundingClientRect(), cs=getComputedStyle(el); return r.width>0&&r.height>0&&cs.visibility!=='hidden'&&cs.display!=='none'; };
  const cssPath = el => { const p=[]; while (el && el.nodeType===1 && el!==document.body){ let i=1,s=el; while((s=s.previousElementSibling)) if (s.tagName===el.tagName) i++; p.unshift(el.tagName.toLowerCase()+':nth-of-type('+i+')'); el=el.parentElement;} return 'body > '+p.join(' > '); };
  const radios = {}; for (const r of document.querySelectorAll('input[type=radio],input[type=checkbox]')) if (!r.checked) { const n=r.name||cssPath(r.parentElement); if(!radios[n]) radios[n]=cssPath(r.closest('label')&&vis(r.closest('label'))?r.closest('label'):r); }
  const choiceBtns = [...document.querySelectorAll('[role=radio],[role=option],[aria-pressed=false],button[class*=option i],button[class*=choice i],[class*=tile i] button,[class*=card i][role=button]')].filter(vis).filter(b=>b.getAttribute('aria-checked')!=='true').slice(0,1).map(cssPath);
  const selects = [...document.querySelectorAll('select')].filter(vis).filter(s=>s.selectedIndex<=0&&s.options.length>1).map(cssPath);
  const numbers = [...document.querySelectorAll('input[type=number],input[inputmode=numeric],input[inputmode=decimal]')].filter(vis).filter(i=>!i.value).map(i=>({path:cssPath(i), name:(i.name||i.placeholder||i.getAttribute('aria-label')||'')}));
  const buttons = [...document.querySelectorAll('button,[role=button],a[class*=button i],input[type=submit]')].filter(vis).map(b=>({path:cssPath(b), text:((b.innerText||b.value||b.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim()).slice(0,60), disabled: b.disabled||b.getAttribute('aria-disabled')==='true'}));
  const heading = ([...document.querySelectorAll('h1,h2,legend,[class*=question i]')].filter(vis)[0]||{}).innerText||'';
  return {url: location.href, heading: heading.trim().slice(0,200), radios: Object.values(radios), choiceBtns, selects, numbers, buttons,
          fields: [...document.querySelectorAll('input,select,textarea')].filter(vis).map(i=>({type:i.type||i.tagName.toLowerCase(), name:i.name||'', label:(i.labels&&i.labels[0]?i.labels[0].innerText:'')||i.placeholder||i.getAttribute('aria-label')||''})).slice(0,40)};
}
"""

async def walk_flow(pg, url, out, analyse, JS, max_steps=14):
    st = await pg.evaluate(STEP)
    looks = FLOW_HINT.search(url) or (st['radios'] or st['choiceBtns'] or st['selects']) and any(SAFE_NEXT.match(b['text']) for b in st['buttons'])
    if not looks: return None
    (out / 'flow').mkdir(exist_ok=True)
    steps, last = [], None
    for n in range(max_steps):
        st = await pg.evaluate(STEP)
        await pg.screenshot(path=str(out / 'flow' / ('s%02d.png' % n)))
        d = await pg.evaluate(JS); els, blocks, fams, _ = analyse(d, out)
        step = {'n': n, 'url': st['url'], 'question': st['heading'], 'fields': st['fields'], 'buttons': [b['text'] for b in st['buttons']][:30],
                'screenshot': 'flow/s%02d.png' % n,
                'copy': [{'role': e['copy_role'], 'text': e['text'][:300], 'chars': e['chars']} for e in els if e['text']][:150],
                'components': sorted({e['ui_term'] for e in els} - {'text', 'layout_container'})}
        sigt = (st['url'], st['heading'], len(st['fields']))
        if sigt == last: step['stopped'] = 'no progress'; steps.append(step); break
        last = sigt
        try:
            for p in st['radios'][:6] + st['choiceBtns'][:1]:
                await pg.locator(p).first.click(timeout=2500); await pg.wait_for_timeout(300)
            for p in st['selects'][:6]:
                await pg.locator(p).first.select_option(index=1, timeout=2500)
            for f in st['numbers'][:4]:
                v = '300000' if re.search(r'price|value|amount|budget|loan|income|salary', f['name'], re.I) else '3'
                await pg.locator(f['path']).first.fill(v, timeout=2500)
        except Exception as e:
            step['fill_error'] = str(e)[:120]
        await pg.wait_for_timeout(800)
        st2 = await pg.evaluate(STEP)
        if st2['url'] != st['url'] or st2['heading'] != st['heading']:
            step['advanced_by'] = 'choice'; steps.append(step); continue      # choosing an option moved the wizard on
        nxt = [b for b in st2['buttons'] if SAFE_NEXT.match(b['text']) and not FORBID.search(b['text']) and not b['disabled']]
        if not nxt:   # answers shown as plain buttons ("From my website or RSS feed") -> pick the first option-like one
            opts = [b for b in st2['buttons'] if 8 <= len(b['text']) <= 90 and not FORBID.search(b['text']) and not b['disabled']
                    and not re.search(r'(log ?in|sign ?in|theme|chat|menu|language|cookie|close|back|help)', b['text'], re.I)
                    and ' > header' not in b['path'] and ' > nav' not in b['path']]
            if opts:
                try:
                    await pg.locator(opts[0]['path']).first.click(timeout=3000); await pg.wait_for_timeout(1800)
                    st3 = await pg.evaluate(STEP)
                    if st3['url'] != st2['url'] or st3['heading'] != st2['heading'] or len(st3['fields']) != len(st2['fields']):
                        step['advanced_by'] = 'option: ' + opts[0]['text']; step['options_offered'] = [o['text'] for o in opts][:12]
                        steps.append(step); continue
                except Exception: pass
        if not nxt:
            step['stopped'] = 'no safe next button (final step or needs personal details): ' + ', '.join(b['text'] for b in st2['buttons'] if b['text'])[:200]
            steps.append(step); break
        step['advanced_by'] = nxt[0]['text']; steps.append(step)
        try:
            await pg.locator(nxt[0]['path']).first.click(timeout=3000); await pg.wait_for_timeout(1800)
        except Exception as e:
            step['stopped'] = 'click failed ' + str(e)[:100]; break
    (out / 'flow.json').write_text(json.dumps({'start_url': url, 'steps': steps}, ensure_ascii=False, indent=1), encoding='utf-8')
    try: await pg.goto(url, wait_until='domcontentloaded', timeout=45000); await pg.wait_for_timeout(1500)
    except Exception: pass
    return {'steps': len(steps), 'last': steps[-1].get('stopped', '') if steps else ''}


TOOL_SAMPLES = [
    (r'note|notepad|text|write|editor|doc', "Project kickoff notes\nAgenda: goals, owners, timeline\n- Confirm scope by Friday\n- Draft brand board\n- Book user interviews"),
    (r'diagram|flowchart|mind ?map', "Customer onboarding flow: sign up, verify email, choose plan, first project, invite team"),
    (r'rewrite|paraphras|grammar|summar', "Our product helps small teams keep every note, task and file in one calm place so nothing gets lost."),
    (r'citation|cite', "https://en.wikipedia.org/wiki/Note-taking"),
    (r'voice|speech|audio', "Welcome to the weekly update. Here are the three things that changed this week."),
    (r'.', "Plan a 30 minute team meeting about the new website launch"),
]

EDITOR = r"""
() => {
  const vis = el => { const r=el.getBoundingClientRect(), cs=getComputedStyle(el); return r.width>200&&r.height>40&&cs.visibility!=='hidden'&&cs.display!=='none'; };
  const cssPath = el => { const p=[]; while (el && el.nodeType===1 && el!==document.body){ let i=1,s=el; while((s=s.previousElementSibling)) if (s.tagName===el.tagName) i++; p.unshift(el.tagName.toLowerCase()+':nth-of-type('+i+')'); el=el.parentElement;} return 'body > '+p.join(' > '); };
  const c = [...document.querySelectorAll('[contenteditable=true],[contenteditable=""],textarea,.ProseMirror,.ql-editor,[role=textbox]')].filter(vis)
            .filter(e=>!e.closest('header,nav,footer'));
  c.sort((a,b)=>b.getBoundingClientRect().width*b.getBoundingClientRect().height - a.getBoundingClientRect().width*a.getBoundingClientRect().height);
  if (!c.length) return null;
  const e=c[0], r=e.getBoundingClientRect();
  return {path: cssPath(e), tag: e.tagName.toLowerCase(), rich: e.isContentEditable, w: Math.round(r.width), h: Math.round(r.height),
          placeholder: e.getAttribute('placeholder')||e.getAttribute('data-placeholder')||e.getAttribute('aria-label')||''};
}
"""

async def exercise_tool(pg, url, out, analyse, JS):
    """Tool pages (notepads, generators, editors): type realistic sample content, select it, then exercise every
    control against the filled state. Each state is recorded with a screenshot."""
    ed, frame = None, pg
    for fr in [pg.main_frame] + [f for f in pg.frames if f != pg.main_frame]:
        try: e = await fr.evaluate(EDITOR)
        except Exception: continue
        if e and (not ed or e['w'] * e['h'] > ed['w'] * ed['h']): ed, frame = e, fr
    if not ed: return None
    ed['frame_url'] = frame.url if frame != pg.main_frame else ''
    (out / 'tool').mkdir(exist_ok=True)
    sample = next(t for rx, t in TOOL_SAMPLES if re.search(rx, url + ' ' + ed['placeholder'], re.I))
    res = {'editor': ed, 'sample_text': sample, 'states': []}
    try:
        loc = (frame if frame != pg.main_frame else pg).locator(ed['path']).first
        await loc.scroll_into_view_if_needed(timeout=3000)
        await pg.screenshot(path=str(out / 'tool' / 't00_empty.png')); res['states'].append({'state': 'empty', 'screenshot': 'tool/t00_empty.png'})
        try: await loc.click(timeout=3000)
        except Exception:
            await clear_gates(pg, out)
            try: await loc.click(timeout=3000, force=True)
            except Exception: await loc.evaluate('e=>e.focus()')
        await pg.keyboard.type(sample, delay=8)
        await pg.wait_for_timeout(900)
        await pg.screenshot(path=str(out / 'tool' / 't01_filled.png')); res['states'].append({'state': 'filled', 'screenshot': 'tool/t01_filled.png'})
        if ed['rich']:
            await pg.keyboard.press('Control+A'); await pg.wait_for_timeout(300)
            await pg.screenshot(path=str(out / 'tool' / 't02_selected.png')); res['states'].append({'state': 'text_selected', 'screenshot': 'tool/t02_selected.png'})
        d = await pg.evaluate(JS); els, blocks, fams, _ = analyse(d, out)
        res['filled_components'] = sorted({e['ui_term'] for e in els} - {'text', 'layout_container'})
        res['controls'] = await explore(pg, url, out / 'tool', analyse, JS, max_n=40, reload_url=False)
    except Exception as e:
        res['error'] = str(e)[:200]
    (out / 'tool.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    try: await pg.goto(url, wait_until='domcontentloaded', timeout=45000); await pg.wait_for_timeout(2000)
    except Exception: pass
    return {'editor': ed['tag'], 'rich': ed['rich'], 'controls': (res.get('controls') or {}).get('effects'), 'error': res.get('error', '')}


SOFT = re.compile(r"^\s*(maybe later|not now|no,? thanks|no thank you|skip|close|dismiss|continue without|later|×|✕|x|reject all|decline|only necessary|necessary only|accept all|accept|got it|ok|i understand)\s*$", re.I)

GATE = r"""
() => {
  const vis = el => { const r=el.getBoundingClientRect(), cs=getComputedStyle(el); return r.width>0&&r.height>0&&cs.visibility!=='hidden'&&cs.display!=='none'&&+cs.opacity>0.05; };
  const cssPath = el => { const p=[]; while (el && el.nodeType===1 && el!==document.body){ let i=1,s=el; while((s=s.previousElementSibling)) if (s.tagName===el.tagName) i++; p.unshift(el.tagName.toLowerCase()+':nth-of-type('+i+')'); el=el.parentElement;} return 'body > '+p.join(' > '); };
  const boxes = [...document.querySelectorAll('[role=dialog],[aria-modal=true],dialog[open],#onetrust-banner-sdk,[id*=cookie i],[class*=cookie i],[class*=consent i],[class*=modal i],[class*=popup i],[class*=paywall i],[class*=gate i]')]
     .filter(vis).filter(d=>{const r=d.getBoundingClientRect(); return r.width>200&&r.height>80;});
  return boxes.slice(0,6).map(d=>{
    const r=d.getBoundingClientRect(); const cookie=/cookie|consent|onetrust|privacy/i.test(d.id+' '+d.className+' '+(d.innerText||'').slice(0,300));
    const btns=[...d.querySelectorAll('button,a,[role=button]')].filter(vis).map(b=>({path:cssPath(b), text:((b.innerText||'')+' '+(b.getAttribute('aria-label')||'')).replace(/\s+/g,' ').trim().slice(0,60)}));
    return {kind: cookie?'cookie_banner':'gate_modal', path: cssPath(d), x:r.left, y:r.top, w:r.width, h:r.height, text:(d.innerText||'').replace(/\s+/g,' ').trim().slice(0,600), buttons: btns};
  });
}
"""

async def clear_gates(pg, out, rounds=3):
    """Record any gate / upsell / cookie overlay (screenshot + copy + buttons), then dismiss it with the softest option."""
    found = []
    (out / 'gates').mkdir(exist_ok=True)
    for r in range(rounds):
        boxes = []
        for fr in pg.frames:
            try:
                for b in await fr.evaluate(GATE): b['_frame'] = fr; b['frame_url'] = fr.url if fr != pg.main_frame else ''; boxes.append(b)
            except Exception: pass
        if not boxes: break
        for i, b in enumerate(boxes):
            fr = b.pop('_frame')
            shot = 'gates/g%d_%d.png' % (r, i)
            try: await pg.screenshot(path=str(out / shot))
            except Exception: shot = ''
            b['screenshot'] = shot
            labels = sorted(b['buttons'], key=lambda x: 0 if re.match(r'^\s*(maybe later|not now|no,? thanks|skip|close|dismiss|reject|decline|only necessary)', x['text'], re.I) else 1)
            hit = next((x for x in labels if SOFT.match(x['text']) or re.search(r'close', x['text'], re.I)), None)
            b['dismissed_with'] = hit['text'] if hit else ''
            if hit:
                try: await fr.locator(hit['path']).first.click(timeout=2500, force=True); await pg.wait_for_timeout(700)
                except Exception: hit = None
            if not hit:
                try:
                    await pg.keyboard.press('Escape'); await pg.wait_for_timeout(300)
                    await fr.evaluate("p=>{const e=document.querySelector(p); if(e) e.remove();}", b['path'])
                    b['dismissed_with'] = 'removed'
                except Exception: pass
            found.append(b)
        await pg.wait_for_timeout(900)
    if found:
        (out / 'gates.json').write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding='utf-8')
    return [{'kind': b['kind'], 'text': b['text'][:120], 'dismissed_with': b['dismissed_with']} for b in found]


SOFT_FIND = r"""
() => {
  const rx = /^\s*(maybe later|not now|no,? thanks|no thank you|skip( for now)?|continue as guest|continue without( signing in)?|remind me later)\s*$/i;
  const vis = el => { const r=el.getBoundingClientRect(), cs=getComputedStyle(el); return r.width>0&&r.height>0&&cs.visibility!=='hidden'&&cs.display!=='none'; };
  const cssPath = el => { const p=[]; while (el && el.nodeType===1 && el!==document.body){ let i=1,s=el; while((s=s.previousElementSibling)) if (s.tagName===el.tagName) i++; p.unshift(el.tagName.toLowerCase()+':nth-of-type('+i+')'); el=el.parentElement;} return 'body > '+p.join(' > '); };
  for (const el of document.querySelectorAll('button,a,[role=button],span,div,p')) {
    if (el.children.length > 2 || !vis(el)) continue;
    const t = (el.innerText||'').trim();
    if (t.length < 40 && rx.test(t)) {
      let box = el; for (let i=0;i<8 && box.parentElement;i++){ box = box.parentElement; const r=box.getBoundingClientRect(); if (r.width>280 && r.height>200) break; }
      return {path: cssPath(el), text: t, gate_text: (box.innerText||'').replace(/\s+/g,' ').trim().slice(0,600)};
    }
  }
  return null;
}
"""

_clear_gates_std = clear_gates
async def clear_gates(pg, out, rounds=3):
    found = await _clear_gates_std(pg, out, rounds)
    (out / 'gates').mkdir(exist_ok=True)
    for r in range(rounds):
        hit = None
        for fr in pg.frames:
            try: h = await fr.evaluate(SOFT_FIND)
            except Exception: continue
            if h: hit = (fr, h); break
        if not hit: break
        fr, h = hit
        shot = 'gates/soft%d.png' % r
        try: await pg.screenshot(path=str(out / shot))
        except Exception: shot = ''
        try: await fr.locator(h['path']).first.click(timeout=2500, force=True); await pg.wait_for_timeout(900)
        except Exception: pass
        rec = {'kind': 'gate_modal', 'text': h['gate_text'], 'dismissed_with': h['text'], 'screenshot': shot, 'frame_url': fr.url if fr != pg.main_frame else ''}
        found.append(rec)
        prev = json.loads((out / 'gates.json').read_text(encoding='utf-8')) if (out / 'gates.json').exists() else []
        (out / 'gates.json').write_text(json.dumps(prev + [rec], ensure_ascii=False, indent=1), encoding='utf-8')
    return [{'kind': b['kind'], 'text': b['text'][:120], 'dismissed_with': b['dismissed_with']} for b in found]
