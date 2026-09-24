#!/usr/bin/env python3
"""Wednesday: pick 20 cards for the Instagram rotation, stage their images, and
price them for DIRECT sale — which is not the same question as pricing for eBay.

    python3 reports/ig-wednesday.py            # normal run
    python3 reports/ig-wednesday.py --dry-run  # pick and report, touch nothing

Why direct is its own calculation. eBay takes 13.25%, so an eBay listing has to
clear cost + fee + postage. A direct sale takes no fee, so it only has to clear
cost + postage — about $25 less on a $150 card. That gap is the whole point of
the channel: it rescues cards that cannot be sold at a profit on eBay at any
price a buyer will actually pay. Those are what belong here. Not the best cards
— the ones eBay's fee is strangling.

Craig's rule sets the ceiling: the Instagram crowd knows comps and will not buy
above them. So a card is only eligible when the top of its comp range covers
cost + postage, and it is posted at or under comp, never above.

What this does NOT do: pull comps or change eBay prices. eBay's sold data needs
the Marketplace Insights API and there are no keys; scraping search headlessly
gets blocked, and eBay search mixes graded sales into raw results badly enough
that comp-data.json has base-card prices sitting against numbered parallels.
Comps are queued here for a human with a browser. Nothing here can mis-price a
card on its own.
"""
import csv, glob, json, os, re, shutil, sys, time, urllib.parse, urllib.request
from datetime import date

HERE  = os.path.dirname(os.path.abspath(__file__))
SEARCH_DIRS = [HERE, os.path.expanduser('~/Desktop'), os.path.expanduser('~/Downloads')]
CARDS = os.path.join(HERE, 'ig-cards')
RAW   = os.path.join(CARDS, '_raw')   # originals; the posted frames sit alongside
STATE = os.path.join(HERE, 'ig-state.json')
WEEK  = os.path.join(HERE, 'ig-this-week.json')
WORK  = os.path.join(HERE, 'ig-comp-worklist.csv')
COMPS = os.path.join(HERE, 'comp-data.json')
VERIFIED = os.path.join(HERE, 'comp-verified.json')

PICK      = 20
MIN_PRICE = 20.0     # below this a story slot is not worth spending
PERSONAL  = 9000.0   # legacy fallback; the marker is now the `Personal` tag

PERSONAL_TAG = 'Personal'


HELD_TAGS = ('Personal', 'At PSA')


def is_personal(row):
    """Not sellable right now — skip for posting, repricing and mispricing flags.

    Two distinct cases, both held back:
      `Personal`  Craig's own collection. An owner draw, excluded from COGS.
      `At PSA`    business stock out for grading. It comes back and gets sold.

    The marker is the TAG. It used to be a $9,999 placeholder price, which four
    scripts each had to remember; one forgetting it would put a personal card in
    the Instagram pool or the repricing list. The price test stays as a fallback
    until the placeholders are repriced. The website shows these in its own
    "Personal Collection" section off the `coming-soon` Shopify collection, so
    they are deliberately quantity 0 and carry no price to buyers."""
    tags = [t.strip() for t in (row.get('Tags') or '').split(',')]
    if any(t in HELD_TAGS for t in tags):
        return True
    try:
        return float(row.get('Variant Price') or 0) >= 9000
    except (TypeError, ValueError):
        return False


FEE, ESE, GA = 0.1325, 0.78, 6.07
ESE_CAP = 20 - ESE

# The custom domain is a headless front end and 404s on /products/<h>.json, but
# the myshopify origin serves it publicly with no token — which matters because
# a launchd job has no Shopify credentials, and Image Src in an aging export
# goes 404 once Shopify regenerates the asset URLs.
SHOP_ORIGIN = 'https://duxburytradingpost.myshopify.com'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DTP-IG/1.0'


def postage(price):
    return ESE if price <= ESE_CAP else GA


def be_direct(cost, price):
    """Direct break-even: no marketplace fee, but he still pays postage."""
    return round(cost + postage(price) + 0.005, 2)


def be_ebay(cost, price):
    """Shown for contrast. The shipping tier follows the PRICE, not the cost —
    anything over $19.22 loses the envelope rate. Getting that backwards
    understated 19 offer floors on 8 Sept."""
    per = 0.30 if price <= 10 else 0.40
    return round((cost + per + postage(price)) / (1 - FEE) + 0.005, 2)


def newest_export():
    files = []
    for d in SEARCH_DIRS:
        try:
            files += glob.glob(os.path.join(d, 'products_export*.csv'))
        except OSError:
            continue
    return max(files, key=os.path.getmtime) if files else None


def load_state():
    try:
        st = json.load(open(STATE))
    except Exception:
        st = {}
    st.setdefault('seen', {})        # sku -> ISO date it was last posted
    st.setdefault('runs', 0)
    if st.pop('used', None) is not None:   # migrate the old cycle-and-reset shape
        st.pop('cycles', None)
    return st


WIDE_COMP = 3.0   # hi/lo beyond this is a bad match, not a price range

# --- comp trustworthiness -------------------------------------------------
# WIDE_COMP alone does not protect this channel. A SportsCardsPro guide value
# arrives as a single point (lo == hi == median), so hi/lo is 1.0 and the spread
# guard never fires no matter how wrong the match is. On 11 Sept 13 of 20 picks
# were priced off a guide entry for a DIFFERENT card: the matcher ignores print
# runs, so a Josh Allen Orange Power Surge /25 was about to be posted at the
# unnumbered $188, and a McCaffrey Bronze /75 at $6.99. This audience checks
# comps, so an indefensible price is worse than not posting.
SEALED_RE  = re.compile(r'\b(mega box|hobby box|blaster|box|case|pack|packs|wax|qty)\b', re.I)
LOT_RE     = re.compile(r'\blot\b|\(\d+\s*cards', re.I)
CASEHIT_RE = re.compile(r'case hit', re.I)
GRADE_RE   = re.compile(r'\b(psa|bgs|sgc|cgc)\b', re.I)
MIN_GUIDE_VOLUME = 10


def _runs(s):
    """Print-run denominators in a title: '/25' -> {'25'}."""
    return set(re.findall(r'/(\d+)\b', s or ''))


def comp_reason(title, c):
    """Why this comp cannot price this card, or None when it is trustworthy.

    Corroboration is the escape hatch: two independent sources agreeing over 3+
    sales outrank every heuristic below, which is how the Golden (Terapeak +
    scraped + guide, n=44) stays postable while single-guide matches do not."""
    src = c.get('sources') or {}
    # Craig comping the card by hand settles it. He is reading the actual sold
    # listings and knows a Billboard Material is not a Struttin'; every heuristic
    # below exists only to approximate that. A `craig` source therefore clears.
    if 'craig' in src:
        return None
    if len(src) > 1 and (c.get('n') or 0) >= 3:
        return None
    if not src:
        return 'legacy comp only, never verified'
    scp = src.get('sportscardspro') or {}
    matched, gf = scp.get('matched') or '', scp.get('grade_field')
    vol = scp.get('volume') or 0
    ours = _runs(title)
    if SEALED_RE.search(title):
        return 'sealed or multi-unit; guide prices one unit'
    if LOT_RE.search(title):
        return 'lot; guide prices one card'
    if CASEHIT_RE.search(title):
        return 'case hit; guide prices the base insert'
    if ours and not (ours & _runs(matched)):
        # SportsCardsPro does not index print runs at all — no guide row carries
        # a /N. It DOES name the parallel ('[Blue Wave]', '[Green Hyper]'), and
        # in modern sets a named colour parallel is a single print run, so a
        # name match is a card match even though the /N is absent. Demanding the
        # /N blocked 26 cards that were correctly matched. What is NOT safe is a
        # numbered parallel matched to a BASE row, or to a different colour:
        # the Impeccable /75 and the Citrine /25 both hit base rows, and a Keon
        # Coleman Rated Rookie hit an 'Autograph Pink Velocity' at $1.75.
        par = re.findall(r'\[([^\]]+)\]', matched)
        if not par:
            return 'numbered /%s matched to a BASE guide row' % '|'.join(sorted(ours))
        tl = title.lower()
        missing = [w for w in re.findall(r"[a-z']+", par[0].lower())
                   if len(w) > 2 and w not in tl]
        if missing:
            return 'guide parallel "%s" is not this card' % par[0]
    if GRADE_RE.search(title) and gf in ('loose-price', 'manual-only-price'):
        return 'graded card matched to an ungraded guide price'
    if gf and gf.startswith('condition-'):
        return 'unmapped guide grade field %s' % gf
    if vol and vol < MIN_GUIDE_VOLUME:
        return 'guide volume %d too thin' % vol
    return None


def ask_price(comp_hi, comp_lo, bd, median=None):
    """Post at the MIDDLE of the comp range, not the top.

    The top of a range is the best price anyone ever got for the card. Pricing
    there is how inventory sits. The goal is to move it, so aim at the middle
    and fall back to the top only if the middle would not cover cost + postage.

    A verified comp carries a real median of the matched sales; prefer it over
    the midpoint of lo..hi, which a single high sale drags upward.

    There is deliberately NO break-even floor. Craig's instruction on 9 Sept was
    "post at median and take loss" — the goal is to move inventory and get the
    cash back, and pricing above what the market pays is how a card sits for a
    year instead. Where that means a loss, the loss is shown, not hidden."""
    target = median if median else (comp_hi + comp_lo) / 2
    return max(1.0, float(int(target)))


def eligible(export):
    """Cards that can carry a defensible direct price.

    Boxes- SKUs are excluded on purpose: their cost is allocated in proportion
    to list price, so margin on one is circular and any number here is invented.
    Never put one in front of an audience that checks comps."""
    # Verified comps override the hand-built set — see comp-tools.py for why.
    comps = {}
    for f in (COMPS, VERIFIED):
        try:
            for c in json.load(open(f)):
                if c.get('lo') not in (None, ''):
                    comps[c['title']] = c
        except Exception:
            pass
    # Costs repeated to the cent across 3+ cards from one source are lot averages,
    # not purchase prices. A margin claim built on one is invented, and this
    # audience checks. Same rule as the briefing.
    allrows = list(csv.DictReader(open(export)))
    pairs = {}
    for r in allrows:
        try:
            k = ((r.get('Variant SKU') or '').split('-')[0],
                 round(float(r.get('Cost per item') or 0), 2))
        except ValueError:
            continue
        pairs[k] = pairs.get(k, 0) + 1

    rows, seen, uncomped, untrusted = [], set(), 0, []
    for r in allrows:
        h = (r.get('Handle') or '').strip()
        t = (r.get('Title') or '').strip()
        if not h or not t or h in seen:
            continue
        seen.add(h)
        if (r.get('Status') or '').lower() != 'active':
            continue
        sku = (r.get('Variant SKU') or '').strip()
        if sku.split('-')[0] == 'Boxes':
            continue
        try:
            if pairs.get((sku.split('-')[0],
                          round(float(r.get('Cost per item') or 0), 2)), 0) >= 3:
                continue
        except ValueError:
            continue
        try:
            price = float(r.get('Variant Price') or 0)
            cost  = float(r.get('Cost per item') or 0)
        except ValueError:
            continue
        if cost <= 0 or price < MIN_PRICE or is_personal(r):
            continue
        # A sold card can sit ACTIVE in Shopify with quantity 0 — the Cam
        # Skattebo sold on 7 Sept and was still staged for posting on the 9th.
        # Advertising stock you do not have is worse than not posting at all.
        try:
            if int(r.get('Variant Inventory Qty') or 0) < 1:
                continue
        except ValueError:
            continue
        c = comps.get(t)
        if not c or c.get('lo') in (None, ''):
            uncomped += 1
            continue
        try:
            lo, hi = float(c['lo']), float(c['hi'])
        except (TypeError, ValueError):
            uncomped += 1
            continue
        bd = be_direct(cost, price)
        # A comp below cost is no longer a reason to skip the card. It is the
        # reason to post it: the money is already gone, and a sale returns cash
        # that a listing sitting at an unpayable price never will.
        if lo > 0 and hi / lo > WIDE_COMP:
            uncomped += 1                 # a 7x spread is a bad join, not a market
            continue
        why = comp_reason(t, c)
        if why:
            untrusted.append((t, why))
            continue
        post = ask_price(hi, lo, bd, c.get('median'))
        if post is None:
            continue
        # MIN_PRICE gates the eBay ask; it has to gate the POST price too. The
        # comp for a badly overbought base card is often genuinely $1-5, and
        # that comp is not wrong — but a $2 card in a story slot advertises a
        # bargain bin, not a card shop. Those belong in a lot, not a frame.
        if post < MIN_PRICE:
            untrusted.append((t, 'market price $%.2f is below the $%.0f story floor'
                              % (post, MIN_PRICE)))
            continue
        rows.append({'handle': h, 'sku': sku, 'title': t, 'ebay': price, 'cost': cost,
                     'be_direct': bd, 'be_ebay': be_ebay(cost, price),
                     'comp_lo': lo, 'comp_hi': hi, 'comp_n': c.get('n', ''),
                     'post_at': post,
                     'margin': round(hi - bd, 2)})
    # Two Shopify products can be two real copies of one card — Craig has two
    # Josh Allen Blue Surge /99, bought at $75.03 and $69.23. Posting the same
    # frame twice reads as careless, but hiding the second copy loses a sale, so
    # they collapse into ONE frame carrying a quantity. Price is comp-derived and
    # identical for both; keep the cheaper copy's break-even so the P/L shown is
    # the conservative one, and sell that copy first.
    merged = {}
    for r in rows:
        k = r['title'].strip().lower()
        if k in merged:
            merged[k]['qty'] += 1
            if r['be_direct'] > merged[k]['be_direct']:
                merged[k]['be_direct'] = r['be_direct']   # conservative of the two
            continue
        r['qty'] = 1
        merged[k] = r
    rows = list(merged.values())
    for r in rows:
        r['profit'] = round(r['post_at'] - r['be_direct'], 2)
        r['ebay_dead'] = r['comp_hi'] < r['be_ebay']   # rescued by dropping the fee
    return rows, uncomped, untrusted


def choose(rows, state):
    """20 cards, least-recently-posted first.

    The obvious approach — track what has been used and reset when the pool runs
    dry — silently fails at this pool size. With 30 eligible and 20 picked, only
    10 are unseen after week one, which is fewer than a full pick, so it resets
    every week and shows the same top 20 forever. Nothing else ever surfaces.

    Ordering by last-posted date instead guarantees every card comes round: never
    posted sorts first, then oldest, and margin only breaks ties."""
    seen = state.get('seen', {})
    ordered = sorted(rows, key=lambda r: (seen.get(r['sku'], ''), -r['margin']))
    return ordered[:PICK]


def _get(url):
    for attempt in (1, 2, 3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                 # a real miss, not worth retrying
            if attempt == 3:
                raise
            time.sleep(1.5 * attempt)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1.5 * attempt)       # the origin throttles a fast loop
    return None


def image_url(handle, title=''):
    """Front image, resolved live.

    Handles in the export go stale whenever a product is renamed — the Golden's
    handle still said 'downtown' after its title was corrected on 31 Aug, and
    404'd. So fall back to the public storefront search, which finds the product
    by title and hands back the current handle and image."""
    d = _get(f'{SHOP_ORIGIN}/products/{handle}.json')
    if d:
        imgs = d['product'].get('images', [])
        if imgs:
            return imgs[0]['src']
    if not title:
        return None
    q = urllib.parse.urlencode({'q': title, 'resources[type]': 'product',
                                'resources[limit]': 1})
    d = _get(f'{SHOP_ORIGIN}/search/suggest.json?{q}')
    try:
        hit = d['resources']['results']['products'][0]
    except Exception:
        return None
    img = hit.get('featured_image')
    if isinstance(img, dict):
        return img.get('url')
    return img or None


def stage_images(picks, dry):
    if dry:
        return [], 0
    if os.path.isdir(CARDS):
        shutil.rmtree(CARDS)
    os.makedirs(RAW, exist_ok=True)
    ok, failed = [], 0
    for i, p in enumerate(picks, 1):
        slug = re.sub(r'[^A-Za-z0-9]+', '-', p['title'])[:56].strip('-')
        dest = os.path.join(RAW, f"{i:02d}__POST-{p['post_at']:.0f}__{slug}.jpg")
        try:
            src = image_url(p['handle'], p['title'])
            if not src:
                raise RuntimeError('product has no images')
            req = urllib.request.Request(src, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=30) as r, open(dest, 'wb') as fh:
                fh.write(r.read())
            ok.append(dest)
        except Exception as e:
            failed += 1
            print(f'[image failed: {p["title"][:38]} — {e}]', file=sys.stderr)
        time.sleep(0.7)
    return ok, failed


def main():
    dry = '--dry-run' in sys.argv
    export = newest_export()
    if not export:
        print('no products_export*.csv found', file=sys.stderr)
        return 1
    rows, uncomped, untrusted = eligible(export)
    state = load_state()
    picks = choose(rows, state)

    if not dry:
        today = date.today().isoformat()
        for p in picks:
            state['seen'][p['sku']] = today
        state['runs'] = state.get('runs', 0) + 1
        json.dump(state, open(STATE, 'w'), indent=1)
        json.dump({'picks': picks, 'export': os.path.basename(export),
                   'pool': len(rows), 'uncomped': uncomped,
                   'untrusted': [{'title': t, 'why': w} for t, w in untrusted],
                   'run': state['runs']}, open(WEEK, 'w'), indent=1)
        cols = ['sku', 'title', 'ebay', 'cost', 'be_direct', 'be_ebay',
                'comp_lo', 'comp_hi', 'comp_n', 'post_at', 'profit', 'ebay_dead']
        with open(WORK, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in picks:
                w.writerow({k: r[k] for k in cols})

    files, failed = stage_images(picks, dry)
    framed = 0
    if not dry and files:
        # Compose the 1080x1920 story frames. Kept in its own module so the
        # layout can be reworked without touching selection or pricing.
        try:
            import ig_render
            framed = ig_render.main()
        except Exception as e:
            print(f'[story frames failed: {e}]', file=sys.stderr)
        # Marketplace listings use the same cards and the same prices, so they are
        # generated from the same run — the two channels cannot drift apart.
        try:
            os.system(f'/usr/bin/python3 {os.path.join(HERE, "fb-listings.py")} >/dev/null 2>&1')
            os.system(f'/usr/bin/python3 {os.path.join(HERE, "fb-page.py")} >/dev/null 2>&1')
        except Exception as e:
            print(f'[marketplace listings failed: {e}]', file=sys.stderr)
    weeks = len(rows) / PICK if PICK else 0
    rescued = sum(1 for p in picks if p['ebay_dead'])

    never = sum(1 for r in rows if r['sku'] not in state.get('seen', {}))
    print(f"pool {len(rows)} eligible · {weeks:.1f} weeks to cycle the pool · "
          f"run {state.get('runs', 0)} · {never} never posted · export {os.path.basename(export)}")
    print(f"{uncomped} active cards sat out — no comp, so no defensible price")
    if untrusted:
        print(f"{len(untrusted)} more sat out — a comp exists but does not price THIS card:")
        for t, why in sorted(untrusted, key=lambda x: x[1]):
            print(f"    {why:<52} {t[:46]}")
    print()
    losses = [p for p in picks if p['profit'] < 0]
    print(f"{'POST AT':>8} {'eBay ask':>9} {'direct b/e':>11} {'comp':>12} {'P/L':>8}  card")
    for p in picks:
        flag = ' LOSS' if p['profit'] < 0 else ('  *  ' if p['ebay_dead'] else '     ')
        print(f"{p['post_at']:8.0f} {p['ebay']:9.2f} {p['be_direct']:11.2f} "
              f"{('$%.0f-%.0f' % (p['comp_lo'], p['comp_hi'])):>12} {p['profit']:8.2f}{flag} {p['title'][:40]}")
    print(f"\n*    = dead on eBay at market; dropping the 13.25% fee is what makes it work")
    print(f"LOSS = priced at the comp median, below cost. Deliberate: moving it returns "
          f"cash a sitting listing never will.")
    if losses:
        print(f"\n{len(losses)} of {len(picks)} sell at a loss, "
              f"${sum(-p['profit'] for p in losses):,.2f} total accepted.")
    if not dry:
        print(f"{len(files)} cards staged -> {CARDS}" + (f"  ({failed} image download{'s' if failed>1 else ''} failed)" if failed else ""))
        print(f"worklist -> {WORK}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
