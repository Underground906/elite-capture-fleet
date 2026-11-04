"""circle.so cull (2026-11-04): keep every unique page; repeated templates keep 1-2 examples.
Run logs backed up to _untrimmed_run_logs/ first; page folders are NOT deleted."""
import json, re, subprocess, collections
B = 'r2:enterprise-canon/ui-library-elite/circle.so'
def rc(*a): return subprocess.run(['rclone', *a], capture_output=True, text=True)
parts = sorted(l for l in rc('lsf', B + '/').stdout.split() if l.startswith('run.p') and l.endswith('.jsonl'))
if 'run.p000.jsonl' in rc('lsf', B + '/_untrimmed_run_logs/').stdout.split():
    src = B + '/_untrimmed_run_logs'
else:
    for p in parts: rc('copyto', f'{B}/{p}', f'{B}/_untrimmed_run_logs/{p}')
    src = B + '/_untrimmed_run_logs'
# template -> how many examples to keep (first N by page number)
TEMPLATES = [(r'^/careers/.+', 1, 'careers_job'), (r'^/blog/.+', 1, 'blog_post'), (r'^/customer-stories/.+', 2, 'customer_story'),
             (r'^/event-hub/category/.+', 1, 'event_category'), (r'^/event-hub/.+', 1, 'event_recording'), (r'^/members-only/.+', 1, 'newsletter_issue'),
             (r'^/product-updates/20\d\d$', 1, 'updates_year'), (r'^/product-updates/.+', 1, 'release_note'), (r'^/compare/.+', 2, 'compare_vs'),
             (r'^/(br|de|fr)(/|$)', 0, 'locale_copy'), (r'^/(privacy|terms|cookie-policy)', 0, 'legal')]
per = collections.Counter(); keep, drop = [], []
for p in parts:
    for l in rc('cat', f'{src}/{p}').stdout.splitlines():
        if not l.strip(): continue
        r = json.loads(l); path = '/' + r['url'].split('//', 1)[1].split('/', 1)[1] if '/' in r['url'].split('//', 1)[1] else '/'
        path = path.rstrip('/') or '/'
        t = next(((n, g) for rx, n, g in TEMPLATES if re.search(rx, path)), None)
        if t:
            per[t[1]] += 1
            if per[t[1]] > t[0]: drop.append((p, r, t[1])); continue
        keep.append((p, r))
by = collections.defaultdict(list)
for p, r in keep: by[p].append(json.dumps(r))
for p in parts:
    open('/tmp/' + p, 'w').write('\n'.join(by.get(p, [])) + ('\n' if by.get(p) else ''))
    rc('copyto', '/tmp/' + p, f'{B}/{p}')
open('/tmp/KEEP_TOP_PAGES.txt', 'w').write('\n'.join(f"{r['dir']}\t{r['url']}" for _, r in keep) + '\n')
open('/tmp/DROPPED_PAGES.txt', 'w').write('\n'.join(f"{r['dir']}\t{r['url']}\t{g}" for _, r, g in drop) + '\n')
rc('copyto', '/tmp/KEEP_TOP_PAGES.txt', f'{B}/KEEP_TOP_PAGES.txt'); rc('copyto', '/tmp/DROPPED_PAGES.txt', f'{B}/_untrimmed_run_logs/DROPPED_PAGES.txt')
print('keep', len(keep), 'drop', len(drop)); print(collections.Counter(g for _, _, g in drop))
for _, r, g in drop: print('  drop', g, r['url'])
