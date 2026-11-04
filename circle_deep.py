"""circle.so deep pass (2026-11-04): open mega-menus, exercise the ROI calculator through its
input combinations, and open every tab/disclosure on chosen pages. Never submits forms, never
enters an email. Output -> out/<task>/ (screens + JSON) -> R2 <domain>/deep/<task>/

  python circle_deep.py menus|roi|tabs <url> [<url> ...]
"""
import asyncio, json, re, sys, subprocess
from pathlib import Path
from playwright.async_api import async_playwright

R2 = 'r2:enterprise-canon/ui-library-elite/circle.so/deep'
OUT = Path(__file__).parent / 'out'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'

VIS_TEXT = """() => { const out=[]; const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  while(w.nextNode()){const n=w.currentNode,t=n.textContent.trim(); if(!t) continue; const e=n.parentElement; const r=e.getBoundingClientRect();
   const s=getComputedStyle(e); if(r.width&&r.height&&s.visibility!=='hidden'&&s.display!=='none'&&+s.opacity>0&&r.bottom>0&&r.top<innerHeight*3) out.push(t);} return out; }"""
LINKS_IN = """(el) => [...el.querySelectorAll('a[href]')].filter(a=>{const r=a.getBoundingClientRect();return r.width&&r.height}).map(a=>({
  text:(a.innerText||'').trim().replace(/\\s+/g,' '), href:a.href, aria:a.getAttribute('aria-label')||''}))"""

def slug(s): return re.sub(r'[^A-Za-z0-9]+', '-', s).strip('-')[:60] or 'x'

async def new_page(b):
    ctx = await b.new_context(viewport={'width': 1440, 'height': 900}, user_agent=UA, locale='en-GB')
    pg = await ctx.new_page(); return ctx, pg

async def settle(pg, ms=900):
    try: await pg.wait_for_load_state('networkidle', timeout=8000)
    except Exception: pass
    await pg.wait_for_timeout(ms)

async def dismiss(pg):
    for t in ('Accept', 'Accept all', 'Allow all', 'Got it', 'I agree', 'Close'):
        try:
            b = pg.get_by_role('button', name=re.compile('^' + t + '$', re.I)).first
            if await b.is_visible(timeout=500): await b.click(timeout=1500); await pg.wait_for_timeout(400)
        except Exception: pass

async def menus(b, url, out):
    ctx, pg = await new_page(b); await pg.goto(url, timeout=60000); await settle(pg); await dismiss(pg)
    hdr = pg.locator('header, nav').first
    trig = hdr.locator('button, [aria-haspopup], [aria-expanded]')
    n = await trig.count(); res = []
    before = set(await pg.evaluate(VIS_TEXT))
    for i in range(n):
        t = trig.nth(i)
        try:
            if not await t.is_visible(): continue
            label = (await t.inner_text()).strip() or (await t.get_attribute('aria-label') or f'trigger{i}')
            VL = "()=>[...document.querySelectorAll('a[href]')].filter(a=>{const r=a.getBoundingClientRect();const s=getComputedStyle(a);return r.width>2&&r.height>2&&r.top<innerHeight&&s.visibility!=='hidden'&&+s.opacity>0}).map(a=>{const r=a.getBoundingClientRect();return {text:(a.innerText||'').trim().replace(/\\s+/g,' '),href:a.href,x:r.x,y:r.y,w:r.width,h:r.height}})"
            base = {(l['href'], l['text']) for l in await pg.evaluate(VL)}
            await t.hover(); await pg.wait_for_timeout(900)
            links = [l for l in await pg.evaluate(VL) if (l['href'], l['text']) not in base]
            how = 'hover'
            if not links:
                await t.click(); await pg.wait_for_timeout(1000); how = 'click'
                links = [l for l in await pg.evaluate(VL) if (l['href'], l['text']) not in base]
            now = await pg.evaluate(VIS_TEXT)
            shot = f'menu_{slug(label)}.png'; await pg.screenshot(path=str(out / shot))
            if links:
                x0 = max(0, min(l['x'] for l in links) - 24); y0 = max(0, min(l['y'] for l in links) - 24)
                x1 = min(1440, max(l['x'] + l['w'] for l in links) + 24); y1 = min(900, max(l['y'] + l['h'] for l in links) + 24)
                await pg.screenshot(path=str(out / ('panel_' + shot)), clip=dict(x=x0, y=y0, width=x1 - x0, height=y1 - y0))
            res.append(dict(trigger=label, opened_by=how, links=links, new_visible_text=[x for x in now if x not in before], screenshot=shot, panel_screenshot='panel_' + shot))
            await pg.mouse.move(5, 880); await pg.keyboard.press('Escape'); await pg.wait_for_timeout(500)
        except Exception as e:
            res.append(dict(trigger=i, error=repr(e)[:200]))
    foot = await pg.evaluate("""() => { const f=document.querySelector('footer'); if(!f) return [];
       return [...f.querySelectorAll('a[href]')].map(a=>({text:a.innerText.trim(), href:a.href,
         group:(a.closest('div,ul,section')?.querySelector('h2,h3,h4,h5,h6,p,strong,span')?.innerText||'').trim().slice(0,40)}))}""")
    json.dump(dict(url=url, menus=res, footer=foot), open(out / 'nav_menus.json', 'w'), indent=1)
    await ctx.close()

async def roi(b, url, out):
    ctx, pg = await new_page(b); await pg.goto(url, timeout=60000); await settle(pg); await dismiss(pg)
    main = pg.locator('main').first if await pg.locator('main').count() else pg.locator('body')
    rng = main.locator('input[type=range]'); txt = main.locator('input[type=text], input[type=number], input:not([type])')
    seg = main.locator('button, [role=tab], [role=radio], label')
    seg_labels = []
    for i in range(await seg.count()):
        s = seg.nth(i)
        try:
            if not await s.is_visible(): continue
            l = (await s.inner_text()).strip()
            if l and len(l) < 40 and not re.search(r'save|get started|log in|start free|trial|submit|email me', l, re.I): seg_labels.append(l)
        except Exception: pass
    seg_labels = list(dict.fromkeys(seg_labels))[:8]
    states = []; k = 0
    async def snap(desc):
        nonlocal k
        k += 1; await pg.wait_for_timeout(600)
        vt = await pg.evaluate(VIS_TEXT)
        nums = [t for t in vt if re.search(r'[$£€]\s?[\d,.]+|\b\d[\d,.]*\s?(k|m|%|members|/mo|per month)?\b', t)][:80]
        shot = f'state_{k:02d}.png'
        await main.screenshot(path=str(out / shot), timeout=8000) if await main.count() else await pg.screenshot(path=str(out / shot), full_page=True)
        values = await main.evaluate("(m)=>[...m.querySelectorAll('input')].map(i=>({type:i.type,name:i.name,value:i.value,min:i.min,max:i.max,step:i.step,placeholder:i.placeholder}))")
        states.append(dict(state=k, set=desc, inputs=values, numbers_visible=nums, screenshot=shot))
    await snap('initial')
    prices = ['9.99', '29.99', '99']
    for sl in seg_labels or ['(none)']:
        if sl != '(none)':
            try: await main.get_by_text(sl, exact=True).first.click(timeout=3000)
            except Exception: continue
        for pv in prices:
            for i in range(await txt.count()):
                f = txt.nth(i)
                try:
                    if await f.is_visible() and (await f.get_attribute('type')) != 'email':
                        await f.fill(pv); await f.press('Tab')
                except Exception: pass
            for frac in (0.1, 0.5, 0.95):
                for i in range(await rng.count()):
                    r = rng.nth(i)
                    try:
                        await r.evaluate("(el,f)=>{const mn=+el.min||0,mx=+el.max||100,st=+el.step||1;const v=Math.round((mn+(mx-mn)*f)/st)*st;"
                                         "const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);"
                                         "el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}))}", frac)
                    except Exception: pass
                await snap(dict(segment=sl, price=pv, slider_fraction=frac))
    json.dump(dict(url=url, segments=seg_labels, sliders=await rng.count(), text_inputs=await txt.count(), states=states,
                   rule='email field and Save-my-results never used'), open(out / 'roi_states.json', 'w'), indent=1)
    await ctx.close()

async def tabs(b, url, out):
    ctx, pg = await new_page(b); await pg.goto(url, timeout=60000); await settle(pg); await dismiss(pg)
    main = pg.locator('main').first if await pg.locator('main').count() else pg.locator('body')
    trig = main.locator('[role=tab], button, summary, [aria-expanded], [data-state]')
    res = []; seen = set()
    for i in range(min(await trig.count(), 80)):
        t = trig.nth(i)
        try:
            if not await t.is_visible(): continue
            label = ((await t.inner_text()) or (await t.get_attribute('aria-label')) or '').strip().replace('\n', ' ')[:60]
            if not label or label in seen or re.search(r'start free|trial|sign|log in|book|demo|contact|subscribe', label, re.I): continue
            seen.add(label)
            await t.scroll_into_view_if_needed(timeout=3000)
            before = await pg.evaluate(VIS_TEXT)
            await t.click(timeout=3000); await pg.wait_for_timeout(900)
            after = await pg.evaluate(VIS_TEXT)
            new = [x for x in after if x not in before]
            if not new: continue
            shot = f'tab_{len(res)+1:02d}_{slug(label)}.png'
            await pg.screenshot(path=str(out / shot))
            code = await pg.evaluate("()=>[...document.querySelectorAll('pre,code')].filter(e=>e.getBoundingClientRect().height>0).map(e=>e.innerText).filter(t=>t.length>20).slice(0,20)")
            res.append(dict(trigger=label, new_text=new[:120], code_visible=code, screenshot=shot))
        except Exception: pass
    json.dump(dict(url=url, states=res), open(out / 'tab_states.json', 'w'), indent=1)
    await ctx.close()

async def roi2(b, url, out):
    """Community ROI calculator: custom slider + segmented toggle + fee field -> results heading + chart."""
    ctx, pg = await new_page(b); await pg.goto(url, timeout=60000); await settle(pg); await dismiss(pg)
    states = []
    card = pg.get_by_text('Audience size?').first
    await card.scroll_into_view_if_needed(); await pg.wait_for_timeout(500)
    fee = pg.locator('input[type=text], input:not([type])').filter(has_not=pg.locator('xpath=ancestor::form')).first
    fee = pg.locator('xpath=//*[contains(text(),"Monthly membership fee")]/following::input[1]').first
    track = None
    for sel in ('[role=slider]', '[class*=slider] [class*=thumb]', '[class*=thumb]'):
        if await pg.locator(sel).count(): track = pg.locator(sel).first; break
    k = 0
    for seg in ('Email subscribers', 'Social followers'):
        try: await pg.get_by_text(seg, exact=True).first.click(timeout=3000); await pg.wait_for_timeout(500)
        except Exception: pass
        for fv in ('10', '25', '99'):
            try: await fee.fill(fv); await fee.press('Tab')
            except Exception: pass
            for frac in (0.03, 0.3, 0.65, 0.97):
                try:
                    th = await track.bounding_box()
                    rail = await pg.evaluate("(t)=>{let e=t;for(let i=0;i<4&&e;i++){e=e.parentElement;const r=e.getBoundingClientRect();if(r.width>250) return {x:r.x,y:r.y,w:r.width,h:r.height}} return null}", await track.element_handle())
                    await pg.mouse.move(th['x'] + th['width'] / 2, th['y'] + th['height'] / 2); await pg.mouse.down()
                    await pg.mouse.move(rail['x'] + rail['w'] * frac, th['y'] + th['height'] / 2, steps=12); await pg.mouse.up()
                except Exception as e:
                    pass
                await pg.wait_for_timeout(700); k += 1
                vt = await pg.evaluate(VIS_TEXT)
                res = [t for t in vt if re.search(r'earning|per year|\$[\d,.]+[kM]?|\d+k', t)][:30]
                shot = f'roi_{k:02d}.png'
                try:
                    bb = await card.bounding_box(timeout=3000) or {"y": 0}
                    sy = await pg.evaluate('scrollY')
                    await pg.screenshot(path=str(out / shot), full_page=True, clip=dict(x=100, y=max(0, bb['y'] + sy - 90), width=1240, height=1150))
                except Exception:
                    await pg.screenshot(path=str(out / shot))
                states.append(dict(state=k, audience_type=seg, monthly_fee=fv, slider_fraction=frac, result_text=res,
                                   aria=await track.get_attribute('aria-valuenow') if track else None, screenshot=shot))
    json.dump(dict(url=url, states=states, rule='email field and Save-my-results never used'), open(out / 'roi_states.json', 'w'), indent=1)
    await ctx.close()

async def wizard(b, url, out):
    """Step wizard (pricing calculator): walk 3 paths (first / middle / last option each step). Stops at any email gate."""
    paths = []
    for mode in ('first', 'middle', 'last'):
        ctx, pg = await new_page(b); await pg.goto(url, timeout=60000); await settle(pg); await dismiss(pg)
        try: await pg.get_by_text('Calculate my price', exact=True).first.click(timeout=3000); await pg.wait_for_timeout(900)
        except Exception: pass
        steps = []
        for n in range(16):
            stp = pg.get_by_text(re.compile(r'^Step \d+ of \d+')).first
            try: card = stp.locator('xpath=ancestor::div[.//button][1]'); label = await stp.inner_text(timeout=2000)
            except Exception: card = pg.locator('main'); label = f'end{n}'
            for _ in range(4):
                if await card.locator('button').count() >= 2: break
                card = card.locator('xpath=..')
            q = ''
            try: q = (await card.locator('h1,h2,h3').first.inner_text(timeout=1500)).strip()
            except Exception: pass
            btns = card.locator('button')
            opts = []
            for i in range(await btns.count()):
                t = (await btns.nth(i).inner_text()).strip()
                if t and await btns.nth(i).is_visible() and not re.match(r'^(← ?)?back$', t, re.I): opts.append((i, t))
            nums = card.locator('input[type=number], input[inputmode=numeric], input[type=text]')
            email = await card.locator('input[type=email]').count()
            shot = f'{mode}_{n:02d}.png'
            try: await card.screenshot(path=str(out / shot), timeout=6000)
            except Exception: await pg.screenshot(path=str(out / shot))
            vt = await pg.evaluate(VIS_TEXT)
            steps.append(dict(step=label, question=q, options=[t for _, t in opts], number_inputs=await nums.count(), email_gate=bool(email),
                              result_text=[t for t in vt if re.search(r'\$[\d,.]+|per month|/mo|recommend', t, re.I)][:40], screenshot=shot))
            if email and not [o for o in opts if not re.search(r'save|send|email|get', o[1], re.I)]: steps[-1]['stopped'] = 'email gate - not filled'; break
            for i in range(await nums.count()):
                try:
                    f = nums.nth(i)
                    if await f.is_visible() and (await f.get_attribute('type')) != 'email': await f.fill('500')
                except Exception: pass
            choices = [o for o in opts if not re.search(r'^(next|continue|see|calculate|show)', o[1], re.I)]
            nxt = [o for o in opts if re.search(r'^(next|continue|see|calculate|show)', o[1], re.I)]
            if not choices and not nxt: break
            if choices:
                pick = choices[0] if mode == 'first' else choices[-1] if mode == 'last' else choices[len(choices) // 2]
                steps[-1]['picked'] = pick[1]
                await btns.nth(pick[0]).click(timeout=3000); await pg.wait_for_timeout(900)
            if nxt:
                try: await card.get_by_role('button', name=re.compile(r'^(next|continue|see|calculate|show)', re.I)).first.click(timeout=2500); await pg.wait_for_timeout(1100)
                except Exception: pass
            if steps[-1]['step'] == label and n and steps[-2]['step'] == label and steps[-2].get('question') == q:
                steps[-1]['stopped'] = 'no progress'; break
        await pg.screenshot(path=str(out / f'{mode}_final_full.png'), full_page=True)
        paths.append(dict(mode=mode, steps=steps)); await ctx.close()
    json.dump(dict(url=url, paths=paths, rule='never enters email or submits'), open(out / 'wizard_paths.json', 'w'), indent=1)

async def main(task, urls):
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage'])
        for u in urls:
            name = task + '_' + (slug(u.split('//', 1)[1].split('/', 1)[-1]) if '/' in u.split('//', 1)[1] else 'home')
            out = OUT / name; out.mkdir(parents=True, exist_ok=True)
            try:
                await {'menus': menus, 'roi': roi, 'roi2': roi2, 'wizard': wizard, 'tabs': tabs}[task](b, u, out)
                print('ok', name, flush=True)
            except Exception as e:
                print('FAIL', name, repr(e)[:300], flush=True)
            subprocess.run(['rclone', 'copy', str(out), f'{R2}/{name}'], capture_output=True)
        await b.close()

if __name__ == '__main__':
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
