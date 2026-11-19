#!/usr/bin/env python3
"""Daily market comps for the Sell/Keep page (claude.ai artifact 185vsSmskvCSD5n4RMKXPs).

Craig, 17 Nov 2026: "can you look at market comps and update this site every day". He chose:
the Mac pulls comps every morning and builds the page; Claude publishes it the next time Craig
is in a session ("refresh sell/keep"). Background `claude -p` runs have no Artifact tool, so
this job cannot publish by itself.

    python3 reports/collection-comps.py            # roster + comps + build the page
    python3 reports/collection-comps.py --no-browser   # skip eBay/Card Ladder (SCP + roster only)
    python3 reports/collection-comps.py --build-only   # rebuild the HTML from state, no network

Roster   = ACTIVE products in the Personal Collection (gid://shopify/Collection/314750894166).
           Sold cards (drafted) drop off; new ones are added with a query built from the title.
Comps    = eBay sold (last 60 days) + Card Ladder (graded cards) through Chrome via `claude -p
           --chrome`, plus SportsCardsPro as a reference only (it runs high on new releases).
Market   = median of the 8 most recent matching sales when there are 3+; with 1-2 sales it only
           moves if within 35% of yesterday's value; with none it keeps yesterday's value.
Output   = collection-comps/state.json, collection-comps/collection-review.html (ready to publish),
           collection-comps/changes.txt (what moved, for Claude to tell Craig).
"""
import importlib.util, io, json, math, os, re, statistics, subprocess, sys, urllib.parse, urllib.request
from datetime import datetime, date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, 'collection-comps')
STATE = os.path.join(DIR, 'state.json')
TPL = os.path.join(DIR, 'collection-review.tpl.html')
OUT = os.path.join(DIR, 'collection-review.html')
CHANGES = os.path.join(DIR, 'changes.txt')
COLLECTION = 'gid://shopify/Collection/314750894166'
CLAUDE = os.path.expanduser('~/.local/bin/claude')
TOOLS = ['mcp__claude-in-chrome__tabs_context_mcp', 'mcp__claude-in-chrome__tabs_create_mcp',
         'mcp__claude-in-chrome__navigate', 'mcp__claude-in-chrome__javascript_tool',
         'mcp__claude-in-chrome__tabs_close_mcp']
DAYS = 60
PLAYERS = ['Josh Allen', 'Jayson Tatum', 'Roman Anthony', 'James Cook', 'Keon Coleman', 'Dalton Kincaid',
           'Doug Flutie', 'Payton Tolle', 'James Hagens', 'Drake Maye', 'Jacob Misiorowski']
GRADED = r'\b(psa|bgs|sgc|cgc|beckett|graded|ags|tag)\b'


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, path))
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def log(*a):
    print(datetime.now().strftime('%H:%M:%S'), *a, flush=True)


# ---------- roster ----------
def player_of(t):
    return next((p for p in PLAYERS if p.lower() in t.lower()), 'Other')


def kind_of(title, tags):
    if 'At PSA' in tags:
        return 'At PSA'
    g = re.search(r'\bPSA\s*(10|9)\b', title)
    return f'PSA {g.group(1)}' if g else 'Raw'


def auto_query(title):
    """A starting eBay/Card Ladder query for a card added since the page was built."""
    t = re.sub(r'\s+(Bills|Celtics|Red Sox|Bruins|Patriots|Sabres|Brewers)$', '', title)
    t = re.sub(r'\b(Panini|Topps|RC|SSP|SP|Case Hit)\b', ' ', t)
    num = re.search(r'#\s*([A-Z0-9-]+)', t)
    g = '10' if re.search(r'PSA\s*10', t) else ('9' if re.search(r'PSA\s*9', t) else 'raw')
    q = re.sub(r'#|PSA\s*\d+|\s+', ' ', t).strip().lower()
    q = re.sub(r'\s+', ' ', q) + (' psa 10' if g == '10' else ' psa 9' if g == '9' else '')
    must = re.escape(num.group(1).lower()).replace('\\-', '-?') if num else ''
    sur = player_of(title).split()[-1].lower() if player_of(title) != 'Other' else ''
    must = (f'^(?=.*{sur})' if sur else '^') + (f'(?=.*(?:{must}))' if must else '')
    x = 'psa|bgs|sgc|cgc' if g == 'raw' else ''
    if not re.search(r'/\s?\d', title):          # unnumbered card: keep numbered parallels out
        x = (x + '|' if x else '') + r'/\s?\d{1,3}\b|numbered|superfractor'
    return dict(q=q, m=must, x=x, g=g)


def thumb(url):
    try:
        from PIL import Image
        import base64
        raw = urllib.request.urlopen(url + ('&' if '?' in url else '?') + 'width=240', timeout=30).read()
        im = Image.open(io.BytesIO(raw)).convert('RGB')
        im.thumbnail((107, 180))
        b = io.BytesIO()
        im.save(b, 'JPEG', quality=70)
        return 'data:image/jpeg;base64,' + base64.b64encode(b.getvalue()).decode()
    except Exception as e:
        log('thumb failed', e)
        return ''


def roster(state):
    dl = _load('dl', 'delist-low.py')
    q = ('query($c:String){collection(id:"%s"){products(first:250,after:$c){pageInfo{hasNextPage endCursor}'
         ' nodes{id title status tags featuredImage{url} variants(first:1){nodes{inventoryItem{unitCost{amount}}}}}}}}'
         % COLLECTION)
    nodes, cur = [], None
    while True:
        d = dl.shopify(q, {'c': cur})['collection']['products']
        nodes += d['nodes']
        if not d['pageInfo']['hasNextPage']:
            break
        cur = d['pageInfo']['endCursor']
    live = {n['id'].split('/')[-1]: n for n in nodes if n['status'] == 'ACTIVE'}
    if len(live) < 0.7 * max(1, len(state['cards'])):
        raise SystemExit(f'roster shrank to {len(live)} from {len(state["cards"])} - refusing (Shopify glitch?)')
    gone = [c for c in state['cards'] if c['id'] not in live]
    cards = [c for c in state['cards'] if c['id'] in live]
    have = {c['id'] for c in cards}
    added = []
    for pid, n in live.items():
        c = next((c for c in cards if c['id'] == pid), None)
        if c is None:
            cost = ((n['variants']['nodes'] or [{}])[0].get('inventoryItem') or {}).get('unitCost') or {}
            c = dict(id=pid, title=n['title'], cost=float(cost['amount']) if cost.get('amount') else None,
                     market=None, range='', src='', conf='thin', note='New - first comp', hist=[],
                     img=thumb((n.get('featuredImage') or {}).get('url', '')) if n.get('featuredImage') else '',
                     **auto_query(n['title']))
            cards.append(c)
            added.append(n['title'])
        c['title'] = n['title']
        c['kind'] = kind_of(n['title'], n['tags'])
    state['cards'] = cards
    return [g['title'] for g in gone], added


# ---------- comps ----------
def cl_query(c):
    return re.sub(r'\b(psa|bgs|sgc)\s*\d+\b', '', c['q']).strip()


EBAY_JS = r"""(async()=>{const Q=%s;const G=/\b(psa|bgs|sgc|cgc|beckett|graded|ags|tag)\b/i;const cut=Date.now()-%d*864e5;const out={};
await Promise.all(Q.map(async([k,u,m,x,g])=>{try{const h=await (await fetch(u,{credentials:'include'})).text();
const d=new DOMParser().parseFromString(h,'text/html');const rows=[];
for(const li of d.querySelectorAll('li.s-card')){const t=((li.querySelector('.s-card__title')||{}).textContent||'').replace(/\s+/g,' ').replace(/Opens in a new window or tab/i,'').trim();
const p=((li.querySelector('.s-card__price')||{}).textContent||'');const cap=((li.querySelector('.s-card__caption')||{}).textContent||'');
const pm=p.match(/\$([\d,]+\.?\d*)/);const dm=cap.match(/Sold\s+([A-Z][a-z]{2} \d{1,2}, \d{4})/);if(!pm||!dm||/ to /.test(p))continue;
const dt=new Date(dm[1]);if(dt<cut)continue;if(m&&!new RegExp(m,'i').test(t))continue;if(x&&new RegExp(x,'i').test(t))continue;
if(/\blot\b|reprint|custom|digital|you pick|choose/i.test(t))continue;
if(g==='10'&&!/psa\s*10\b/i.test(t))continue;if(g==='9'&&!/psa\s*9\b/i.test(t))continue;if(g==='raw'&&G.test(t))continue;
rows.push(dt.toISOString().slice(0,10)+'|'+pm[1].replace(/,/g,''));if(rows.length>=10)break}out[k]=rows}catch(e){out[k]=null}}));
return JSON.stringify(out)})()"""

CL_JS = r"""(async()=>{await new Promise(r=>setTimeout(r,5500));const m=%s,x=%s,g=%s;const cut=Date.now()-%d*864e5;
const L=document.body.innerText.split('\n').map(s=>s.trim());const rows=[];const G=/\b(psa|bgs|sgc|cgc|beckett|graded)\b/i;
for(let i=0;i<L.length-5;i++){if(L[i]!=='Date Sold'||L[i+2]!=='Type')continue;const t=(L[i-1]||'')+' '+(L[i-2]||'');
const dt=new Date(L[i+1]);const pm=(L[i+5]||'').match(/\$([\d,]+\.?\d*)/);if(!pm||isNaN(dt)||dt<cut)continue;
if(m&&!new RegExp(m,'i').test(t))continue;if(x&&new RegExp(x,'i').test(t))continue;
if(g==='10'&&!/psa\s*10\b/i.test(t))continue;if(g==='9'&&!/psa\s*9\b/i.test(t))continue;if(g==='raw'&&G.test(t))continue;
rows.push(dt.toISOString().slice(0,10)+'|'+pm[1].replace(/,/g,''));if(rows.length>=10)break}return JSON.stringify(rows)})()"""


def browser_run(rows):
    """rows: [(key, url, js)]. Returns {key: parsed JSON} or None if the run failed."""
    lines = '\n'.join(f'{k}\t{u}\t{js}' for k, u, js in rows)
    prompt = f"""Use the Chrome browser. Create ONE new tab and reuse it for every row below. Each row is
KEY<TAB>URL<TAB>JAVASCRIPT. For each row in order: navigate the tab to URL, wait 2 seconds, then run the
JAVASCRIPT exactly as given with javascript_tool (action javascript_exec). It returns a JSON string.
Do not click anything, do not log in, do not buy, bid or message. If a page fails, record null.
Close the tab at the end. Then output ONE line and nothing after it:
RESULT_JSON: {{"KEY": <the returned JSON, parsed, verbatim>, ...}}  (every KEY present)

{lines}"""
    try:
        p = subprocess.run([CLAUDE, '-p', '--chrome', prompt, '--model', 'claude-sonnet-5-5',
                            '--allowedTools', ','.join(TOOLS)], cwd='/tmp', capture_output=True, text=True,
                           timeout=1800, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        log('!! browser run timed out')
        return None
    m = re.search(r'RESULT_JSON:\s*(\{.*\})\s*$', p.stdout.strip(), re.S)
    if not m:
        log('!! browser run failed:', p.stdout[-800:], p.stderr[-400:])
        return None
    try:
        return json.loads(m.group(1))
    except Exception as e:
        log('!! bad RESULT_JSON', e)
        return None


def browser_comps(cards):
    rows = []
    eb = [(c['id'], 'https://www.ebay.com/sch/i.html?' + urllib.parse.urlencode(
        {'_nkw': c['q'], 'LH_Sold': 1, 'LH_Complete': 1, '_ipg': 120, '_sop': 13}), c['m'], c['x'], c['g'])
          for c in cards]
    for n in range(0, len(eb), 15):
        rows.append((f'E{n}', 'https://www.ebay.com/', EBAY_JS % (json.dumps(eb[n:n + 15]), DAYS)))
    for c in cards:
        if c['g'] in ('10', '9') or c.get('conf') == 'thin':
            url = ('https://app.cardladder.com/sales-history?direction=desc&sort=date&q='
                   + urllib.parse.quote(cl_query(c)))
            rows.append((f'C{c["id"]}', url, CL_JS % (json.dumps(c['m']), json.dumps(c['x']), json.dumps(c['g']), DAYS)))
    ebay, cl, failed = {}, {}, 0
    for n in range(0, len(rows), 12):
        part = browser_run(rows[n:n + 12])
        if part is None:
            failed += 1
            continue
        for k, v in part.items():
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except Exception:
                    v = None
            if k.startswith('E') and isinstance(v, dict):
                ebay.update(v)
            elif k.startswith('C'):
                cl[k[1:]] = v
    log(f'browser: {len(rows)} rows, {failed} chunk(s) failed, eBay {len(ebay)} cards, CL {len(cl)} cards')
    return ebay, cl


def scp_prices(cards):
    S = _load('scp', 'scp-comps.py')
    tok, out = S.token(), {}
    for c in cards:
        try:
            for q in S.query_for(c['title']):
                prods = S.api_products(q, tok)
                if not prods:
                    continue
                b = S.best(S.candidates(prods, c['title']), c['title'])
                if b:
                    v, _ = S.price_for(b, c['title'])
                    if v:
                        out[c['id']] = v
                    break
        except Exception as e:
            log('scp failed', c['title'][:40], e)
    return out


def parse_sales(rows):
    out = []
    for r in rows or []:
        try:
            d, p = r.split('|')
            out.append((d, float(p)))
        except Exception:
            pass
    return out


def fmt(v):
    return f'${v:,.0f}'


def mon(d):
    return datetime.strptime(d, '%Y-%m-%d').strftime('%-d %b')


def value(c, ebay, cl, scp):
    """Update c in place; return (old, new) when the market moved."""
    es, cs = parse_sales(ebay.get(c['id'])), parse_sales(cl.get(c['id']))
    sales = sorted(set(es) | set(cs), reverse=True)
    prev = c.get('market')
    if len(sales) >= 3:                          # drop outliers against the median before taking it
        med = statistics.median(p for _, p in sales)
        sales = [s for s in sales if 0.4 * med <= s[1] <= 2.5 * med]
    recent = sales[:8]
    parts = []
    if es:
        parts.append(f'eBay sold {len(es)} since {mon(min(d for d, _ in es))}')
    if cs:
        parts.append(f'Card Ladder {len(cs)} since {mon(min(d for d, _ in cs))}')
    if scp.get(c['id']):
        parts.append(f'SCP {fmt(scp[c["id"]])}')
    new, note = prev, ''
    if len(recent) >= 3:
        m = statistics.median(p for _, p in recent)
        agree = sum(abs(p - m) <= 0.2 * m for _, p in recent)
        if prev and abs(m - prev) > 0.35 * prev and agree < 5:
            note = f'Sales point to {fmt(m)} - check before relying on it (held at {fmt(prev)})'
        else:
            new = m
        c['conf'] = 'good' if len(recent) >= 5 and agree >= 4 else 'ok'
    elif recent:
        m = statistics.median(p for _, p in recent)
        if prev is None or abs(m - prev) <= 0.35 * prev:
            new = m
        else:
            note = f'{len(recent)} recent sale(s) at {fmt(m)} - not enough to move it from {fmt(prev)}'
        c['conf'] = 'thin'
    elif prev is None and scp.get(c['id']):
        new, c['conf'] = scp[c['id']], 'thin'
        note = 'SCP guide only - no sales found'
    else:
        note = 'No new sales in 60 days - holding the last value' if prev else 'No comps found yet'
        c['conf'] = 'thin'
    if new is not None:
        new = round(new / 5) * 5 if new < 1000 else round(new / 25) * 25
    if recent and new != prev and prev is not None or (recent and prev is None):
        lo, hi = min(p for _, p in recent), max(p for _, p in recent)
        c['range'] = fmt(lo) if lo == hi else f'{fmt(lo)}–{fmt(hi)}'
        c['last_sale'] = recent[0][0]
    if parts and (new != prev or prev is None or len(recent) >= 3 and not note):
        c['src'] = '; '.join(parts)
    c['auto_note'] = note
    c['market'] = new
    c.setdefault('hist', []).append([date.today().isoformat(), new])
    c['hist'] = c['hist'][-30:]
    c['updated'] = date.today().isoformat()
    return (prev, new) if prev and new and abs(new - prev) >= max(5, 0.05 * prev) else None


# ---------- page ----------
def daily(hist):
    """One value per date (the last one written that day), oldest first."""
    d = {}
    for day, v in hist or []:
        if v:
            d[day] = v
    return sorted(d.items())


def portfolio(state):
    """Collection value per day, using TODAY's cards priced as they were on each date (a card with no
    history yet counts at its first value), so the line moves on price changes only, not on buys/sells."""
    series = [(c, daily(c.get('hist'))) for c in state['cards']]
    days = sorted({d for _, h in series for d, _ in h})[-30:]
    out = []
    for day in days:
        tot = 0
        for c, h in series:
            past = [v for d, v in h if d <= day]
            tot += past[-1] if past else (h[0][1] if h else (c.get('market') or 0))
        out.append([day, round(tot)])
    return out


def build(state):
    rows = []
    for c in state['cards']:
        cost, mkt = c.get('cost'), c.get('market') or 0
        floor = math.ceil(cost + 5) if cost else None
        sug = max(mkt, floor or 0)
        sug = int(math.ceil(sug / 5.0) * 5) if sug < 1000 else int(math.ceil(sug / 25.0) * 25)
        note = '; '.join(x for x in (c.get('note', ''), c.get('auto_note', '')) if x)
        t = re.sub(r'\s+(Bills|Celtics|Red Sox|Bruins)$', '', c['title'])
        h = daily(c.get('hist'))
        dv = round(h[-1][1] - h[-2][1]) if len(h) >= 2 else 0           # change since the previous day's value
        dp = round(100.0 * dv / h[-2][1], 1) if len(h) >= 2 and h[-2][1] else 0
        rows.append(dict(id=c['id'], t=t, p=player_of(c['title']), k=c.get('kind', 'Raw'), c=cost, m=mkt, dv=dv, dp=dp,
                         r=c.get('range', ''), s=c.get('src', ''), q=c.get('conf', 'thin'), n=note, f=floor,
                         g=sug, u=bool(floor and floor > mkt), i=c.get('img', '')))
    tpl = open(TPL).read()
    stamp = datetime.now().strftime('%-d %b %Y')
    tpl = re.sub(r'Prices pulled [^.<]*\.', f'Prices pulled {stamp} (updated daily).', tpl)
    body = tpl.replace('__DATA__', json.dumps(rows, separators=(',', ':')).replace('</', '<\\/'))
    body = body.replace('__TREND__', json.dumps(portfolio(state), separators=(',', ':')))
    open(OUT, 'w').write(SKELETON + body + '</body></html>')
    return len(rows)


# The template was written for a claude.ai artifact, which wraps it in this skeleton.
SKELETON = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta name="robots" content="noindex,nofollow"><style>*,*::before,*::after{box-sizing:border-box}'
            ':root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
            'body{margin:0;font:14px/1.45 system-ui,-apple-system,sans-serif}img{max-width:100%}'
            '[hidden]{display:none!important}</style></head><body>')


def upload():
    """Send the built page to duxtradingpost.com/sell-keep (stored in the Worker, never in git)."""
    key = open(os.path.expanduser('~/.dtp-briefing-key')).read().strip()
    req = urllib.request.Request('https://duxtradingpost.com/api/sell-keep/page', data=open(OUT, 'rb').read(),
                                 method='PUT', headers={'X-DTP-Key': key, 'Content-Type': 'text/html',
                                                        'User-Agent': 'dtp-collection-comps'})
    return json.load(urllib.request.urlopen(req, timeout=60))


def main():
    state = json.load(open(STATE))
    if '--build-only' not in sys.argv:
        gone, added = roster(state)
        log(f'roster: {len(state["cards"])} cards, {len(gone)} gone, {len(added)} new')
        scp = scp_prices(state['cards'])
        log(f'SCP: {len(scp)} priced')
        ebay, cl = ({}, {}) if '--no-browser' in sys.argv else browser_comps(state['cards'])
        if not ebay and '--no-browser' not in sys.argv:
            log('!! no eBay data came back - market values left unchanged, NOT a clean refresh')
        moves = []
        for c in state['cards']:
            if ebay or cl:
                mv = value(c, ebay, cl, scp)
                if mv:
                    moves.append((c['title'], *mv))
        state['last_run'] = datetime.now().isoformat(timespec='minutes')
        state['clean'] = bool(ebay)
        json.dump(state, open(STATE + '.tmp', 'w'), indent=1)
        os.replace(STATE + '.tmp', STATE)
        lines = [f'Sell/Keep comps refreshed {state["last_run"]} ({"clean" if ebay else "NO eBay data"})']
        lines += [f'SOLD/REMOVED: {t}' for t in gone] + [f'NEW: {t}' for t in added]
        lines += [f'{t[:70]}: {fmt(a)} -> {fmt(b)} ({(b - a) / a:+.0%})' for t, a, b in
                  sorted(moves, key=lambda m: -abs(m[2] - m[1]))]
        open(CHANGES, 'w').write('\n'.join(lines) + '\n')
        log('\n'.join(lines))
    log(f'built {build(state)} cards -> {OUT}')
    if '--no-upload' not in sys.argv:
        log('uploaded', upload())


if __name__ == '__main__':
    main()
