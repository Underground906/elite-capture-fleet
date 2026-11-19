"""clean_live.py - make the LIVE page clean before the screenshot + HTML are saved:
removes cookie/consent banners and dimming overlays (real DOM removal, not hiding), unlocks scrolling,
forces scroll-reveal / lazy content visible. Returns a dict of what was removed."""
CLEAN_JS = r"""
() => {
  const rep = {removed: 0, kinds: [], revealed: 0};
  const COOKIE = /cookie|consent|gdpr|privacy (settings|preferences|policy)|accept (all|cookies)|reject (all|cookies)|manage (preferences|cookies)|we use (cookies|tracking)|tracking technolog|datenschutz|cookie-einstellungen|alle akzeptieren|ablehnen|zustimmen/i;
  const SEL = ['#onetrust-consent-sdk','#onetrust-banner-sdk','#CybotCookiebotDialog','#CybotCookiebotDialogBodyUnderlay','#usercentrics-root','#usercentrics-cmp-ui',
    '#cookie-law-info-bar','#cookiebanner','#cookie-banner','#cookie-notice','#cookieConsent','#cookie_consent','#gdpr-cookie-notice','#truste-consent-track',
    '.cc-window','.cc-banner','.cookie-banner','.cookie-notice','.cookie-consent','.cookie-popup','.cookiebar','.cookie-bar','.cmp-container','.osano-cm-window',
    '#didomi-host','#didomi-popup','.didomi-popup-container','#sp_message_container_*','[id^=sp_message_container]','.fc-consent-root','#qc-cmp2-container',
    '[id*="cookie" i][role=dialog]','[class*="cookie" i][role=dialog]','[aria-label*="cookie" i]','[aria-label*="consent" i]','[data-cookiebanner]','[data-testid*="cookie" i]',
    '[id*="CookieBanner" i]','[class*="CookieBanner" i]','[class*="cookie-consent" i]','[class*="cookieconsent" i]','[id*="cookieconsent" i]','[class*="consent-banner" i]','[id*="consent-banner" i]',
    '[class*="cmp-" i][class*="banner" i]','[id*="cmp" i][id*="banner" i]','[class*="gdpr" i]','[id*="gdpr" i]'];
  const kill = (el, kind) => { try { el.remove(); rep.removed++; rep.kinds.push(kind); } catch (e) {} };
  for (const s of SEL) { try { document.querySelectorAll(s).forEach(el => { if (el !== document.body && el !== document.documentElement && el.getBoundingClientRect().width > 0) kill(el, s); }); } catch (e) {} }
  // fixed / sticky / high-z boxes whose text is about cookies
  const vw = innerWidth, vh = innerHeight;
  for (const el of Array.from(document.querySelectorAll('body *'))) {
    const cs = getComputedStyle(el); if (!['fixed', 'sticky', 'absolute'].includes(cs.position)) continue;
    const r = el.getBoundingClientRect(); if (r.width < 200 || r.height < 40) continue;
    const t = (el.innerText || '').slice(0, 800);
    if (cs.position !== 'absolute' && COOKIE.test(t) && r.height < vh * 0.9) { kill(el, 'fixed-text'); continue; }
    if (cs.position === 'absolute' && COOKIE.test(t) && t.length < 700 && r.height < 420 && parseInt(cs.zIndex || '0') > 100) { kill(el, 'abs-text'); continue; }
  }
  // dimming backdrops left behind (fixed, covers viewport, almost no text)
  for (const el of Array.from(document.querySelectorAll('body *'))) {
    const cs = getComputedStyle(el); if (cs.position !== 'fixed') continue;
    const r = el.getBoundingClientRect();
    if (r.width >= vw * 0.9 && r.height >= vh * 0.9 && (el.innerText || '').trim().length < 40 && el.querySelectorAll('img,video,canvas,iframe').length === 0) kill(el, 'backdrop');
  }
  // unlock page scroll
  for (const el of [document.documentElement, document.body]) { el.style.setProperty('overflow', 'visible', 'important'); el.style.setProperty('position', 'static', 'important'); el.style.setProperty('height', 'auto', 'important'); }
  document.body.className = document.body.className.replace(/\b(modal-open|no-scroll|noscroll|overflow-hidden|lock-scroll|cc-no-scroll|sp-message-open)\b/g, '');
  // scroll-reveal content that is still invisible
  const st = document.createElement('style'); st.textContent = '*{animation-duration:0s!important;animation-delay:0s!important;transition:none!important}[data-aos]{opacity:1!important;transform:none!important}'; document.head.appendChild(st);
  for (const el of Array.from(document.querySelectorAll('body *'))) {
    const cs = getComputedStyle(el);
    if (cs.opacity === '0' && cs.display !== 'none' && el.getBoundingClientRect().height > 20 && !/modal|dialog|tooltip|popover|dropdown|menu|drawer|overlay|toast/i.test(el.className + ' ' + (el.getAttribute('role') || ''))) { el.style.setProperty('opacity', '1', 'important'); if (cs.transform !== 'none') el.style.setProperty('transform', 'none', 'important'); rep.revealed++; }
  }
  document.querySelectorAll('img[loading=lazy]').forEach(i => i.loading = 'eager');
  document.querySelectorAll('img[data-src]').forEach(i => { if (!i.src || i.src.startsWith('data:')) i.src = i.dataset.src; });
  return rep;
}
"""
async def clean_live(pg):
    out = {'removed': 0, 'kinds': [], 'revealed': 0}
    for _ in range(2):          # twice: banners often re-render after the first removal
        try:
            r = await pg.evaluate(CLEAN_JS); out['removed'] += r['removed']; out['kinds'] += r['kinds']; out['revealed'] += r['revealed']
        except Exception as e:
            out['error'] = str(e)[:100]
        await pg.wait_for_timeout(700)
    return out

def blank_bands(png_path, min_px=900):
    """Tall uniform horizontal bands in a full-page screenshot = content that did not render. Returns list of (y, height)."""
    from PIL import Image
    im = Image.open(png_path).convert('L'); w, h = im.size
    if h > 60000: return []
    sm = im.resize((120, max(1, h // 4)))
    px = sm.load(); W, H = sm.size; bands = []; start = None
    for y in range(H):
        row = [px[x, y] for x in range(W)]; m = sum(row) / W; sd = (sum((v - m) ** 2 for v in row) / W) ** .5
        if sd < 1.2:
            if start is None: start = y
        else:
            if start is not None and (y - start) * 4 >= min_px: bands.append((start * 4, (y - start) * 4))
            start = None
    if start is not None and (H - start) * 4 >= min_px: bands.append((start * 4, (H - start) * 4))
    return bands
