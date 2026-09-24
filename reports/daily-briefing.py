#!/usr/bin/env python3
"""
Duxbury Trading Post — daily morning briefing.

Deliberately not the weekly report. That one answers "what is the state of the
catalogue"; this one answers "what should I do today". Things that barely move
day to day — the below-break-even list, total catalogue P/L — live in the weekly
and are left out here on purpose. A briefing you stop reading is worth nothing.

What it reports:
  · sales since the last run, with realised P/L
  · anything that sold below break-even
  · arrivals due today or overdue
  · listings sitting with no watchers past the release-valve window
  · a NEEDS COMPING queue — cards whose price and cost imply something is wrong

On comping: there is no clean automated source for sold prices on modern sports
cards. Card Ladder has no public API, 130point has none, and eBay's sold data
sits behind Marketplace Insights which needs approval. Worse, most of this
inventory is low-pop numbered parallels that Card Ladder itself cannot value —
it index-estimates them from the purchase price. So this does not pretend to
know the market. It flags the cards where the numbers look wrong and leaves the
judgement to a human with the Price Guide open.

    python3 daily-briefing.py            print to stdout
    python3 daily-briefing.py --email     also send via the Cloudflare Worker
"""
import csv, json, glob, os, re, sys

from briefing_render import Section, render_text, render_html
from datetime import date, datetime, timedelta

HERE    = os.path.dirname(os.path.abspath(__file__))
STATE   = os.path.join(HERE, 'daily-state.json')
LOG     = os.path.join(HERE, '..', 'whatnot', 'purchase-log.xlsx')

# Where to look for the Shopify export, in order. HERE comes first because
# launchd jobs cannot touch ~/Desktop: macOS puts it behind TCC, and a process
# started by launchd has no Full Disk Access, so a glob there silently returns
# nothing and an open() there raises PermissionError. The Desktop stays in the
# list only so a hand-run from a Terminal still finds a file dropped there.
SEARCH_DIRS = [HERE, os.path.expanduser('~/Desktop'), os.path.expanduser('~/Downloads')]

FEE, PER_LOW, PER_HIGH, ESE, GA = 0.1325, 0.30, 0.40, 0.78, 6.07
ESE_MAX_ITEM = 20 - ESE          # item + shipping must clear $20
STALE_DAYS   = 45
ARRIVAL_GRACE = 21       # unarrived this long with no stated ETA is late regardless                # the release-valve window, minus a little warning
OVERPRICED_X = 3.0               # listed at 3x cost with no watchers is a guess, not a price


def net(p):
    ship = ESE if p <= ESE_MAX_ITEM else GA
    return p * (1 - FEE) - (PER_LOW if p <= 10 else PER_HIGH) - ship


def break_even(cost):
    x = 0.01
    while x < 20000:
        if net(x) >= cost:
            return round(x + 0.004, 2)
        x = round(x + 0.01, 2)
    return None


def newest_export():
    files = []
    for d in SEARCH_DIRS:
        try:
            files += glob.glob(os.path.join(d, 'products_export*.csv'))
        except OSError:
            continue          # unreadable directory is a miss, not a crash
    return max(files, key=os.path.getmtime) if files else None


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {'last_run': None, 'sales_seen': [], 'first_seen': {}}


def save_state(s):
    json.dump(s, open(STATE, 'w'), indent=1)


def sheet_rows(name):
    """Read a sheet without openpyxl's full object model — faster and avoids
    holding the workbook open while the user may be editing it."""
    import openpyxl
    wb = openpyxl.load_workbook(LOG, read_only=True, data_only=True)
    ws = wb[name]
    out = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return out


def iso(v):
    s = str(v or '')[:10]
    return s if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s) else None


def money(v):
    return f"${v:,.2f}"


def signed(v):
    return f"{v:+,.2f}"


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def build():
    """Returns (title, meta, sections, stats). Rendering happens in
    briefing_render — this function only decides what is worth saying."""
    today = date.today()
    st = load_state()
    seen = set(st.get('sales_seen', []))
    sections = []

    title = f"DUXBURY TRADING POST — morning briefing   {today}"
    meta = f"since {st['last_run']}" if st.get('last_run') else str(today)

    # ---- sales since the last run -------------------------------------------
    sales = sheet_rows('Sales')[1:]
    new_sales, below = [], []
    for r in sales:
        card = str(r[1] or '')
        if not card or card == 'TOTAL':
            continue
        d = iso(r[0])
        sold = r[3] if isinstance(r[3], (int, float)) else None
        if not d or sold is None:
            continue
        key = f"{d}|{card[:60]}|{sold}"
        if key in seen:
            continue
        seen.add(key)
        basis = r[5] if isinstance(r[5], (int, float)) else None
        fees = r[4] if isinstance(r[4], (int, float)) else None
        pl = (sold - fees - basis) if (fees is not None and basis is not None) else None
        new_sales.append((d, card, sold, pl))
        if pl is not None and pl < 0:
            below.append((card, sold, basis, pl))

    gross = sum(s[2] for s in new_sales)
    known = [s[3] for s in new_sales if s[3] is not None]
    realised = sum(known) if known else None

    sold_rows = []
    for d, card, sold, pl in sorted(new_sales, key=lambda x: -x[2]):
        tone = None if pl is None else ('good' if pl >= 0 else 'bad')
        sold_rows.append([
            (signed(pl) if pl is not None else '?', tone),
            money(sold),
            card[:56],
        ])
    foot = None
    if known:
        foot = (f"Realised P/L on the {plural(len(known), 'sale')} with a cost basis: "
                f"{signed(sum(known))}")
    sections.append(Section(
        'Sold', tone='good' if (realised or 0) >= 0 else 'bad',
        subtitle=(f"{plural(len(new_sales), 'card')}, {money(gross)} gross" if new_sales else None),
        cols=[('P/L', 'r'), ('Price', 'r'), ('Card', 'l')],
        rows=sold_rows, footnote=foot,
        empty='Nothing since the last run.'))

    if below:
        sections.append(Section(
            'Sold below break-even', tone='bad', text_prefix='!!',
            cols=[('P/L', 'r'), ('Sold', 'r'), ('Cost', 'r'), ('Card', 'l')],
            rows=[[(signed(pl), 'bad'), money(sold), money(basis), card[:48]]
                  for card, sold, basis, pl in below]))

    # ---- arrivals due ---------------------------------------------------------
    log = sheet_rows('Purchase log')[1:]
    due, overdue = [], []
    MON = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
           'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}
    for i, r in enumerate(log, start=2):
        status = str(r[12] or '')
        if 'IN TRANSIT' not in status.upper() and 'AWAITING' not in status.upper():
            continue
        card = str(r[2] or '')
        paid = r[3] if isinstance(r[3], (int, float)) else 0
        # dates inside the status text, e.g. "ETA Aug 20-26" or "arriving by Aug 24"
        m = re.findall(r'([A-Z][a-z]{2})\s+(\d{1,2})', status)
        eta = None
        if m:
            last = m[-1]
            try:
                eta = date(today.year, MON[last[0]], int(last[1]))
            except Exception:
                eta = None
        if eta is None:
            # No ETA in the status — which used to mean the row was skipped and
            # never surfaced at all. Four shipments sat in transit from mid-August
            # to 10 Sept that way, $383 of stock nobody was chasing. Fall back to
            # the purchase date: anything unarrived after ARRIVAL_GRACE days is
            # late whether or not someone wrote an ETA.
            try:
                bought = date.fromisoformat(str(r[0])[:10])
            except Exception:
                continue
            if (today - bought).days < ARRIVAL_GRACE:
                continue
            eta = bought + timedelta(days=ARRIVAL_GRACE)
        if eta < today:
            overdue.append((i, card, paid, eta, (today - eta).days))
        elif eta == today:
            due.append((i, card, paid))

    if overdue:
        stuck = sum(o[2] for o in overdue)
        sections.append(Section(
            'Overdue arrivals', tone='warn', text_prefix='!!',
            subtitle=f"{plural(len(overdue), 'shipment')}, {money(stuck)} past ETA",
            cols=[('Late', 'r'), ('Paid', 'r'), ('Row', 'r'), ('Card', 'l')],
            rows=[[(f"{days}d", 'warn'), money(paid), f"row {i}", card[:50]]
                  for i, card, paid, eta, days in sorted(overdue, key=lambda x: -x[4])]))
    if due:
        sections.append(Section(
            'Due today', tone='info',
            cols=[('Paid', 'r'), ('Row', 'r'), ('Card', 'l')],
            rows=[[money(paid), f"row {i}", card[:56]] for i, card, paid in due]))

    _append_deadlines(sections)

    # ---- the catalogue side ---------------------------------------------------
    export = newest_export()
    if not export:
        sections.append(Section(
            'Catalogue checks skipped', tone='muted',
            rows=[], empty='No Shopify export found — export from Shopify to restore '
                           'the comping queue.'))
        _append_grade_scan(sections)
        st['last_run'] = str(today)
        st['sales_seen'] = sorted(seen)
        save_state(st)
        return title, meta, sections, _stats(new_sales, gross, realised, overdue)

    age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(export))).days
    rows = list(csv.DictReader(open(export)))
    prods = {}
    for r in rows:
        h = (r.get('Handle') or '').strip()
        t = (r.get('Title') or '').strip()
        if not h or not t or h in prods:
            continue

        def f(k):
            try:
                return float(r.get(k) or 0)
            except Exception:
                return 0.0
        prods[h] = {'t': t, 'status': (r.get('Status') or '').lower(),
                    'cost': f('Cost per item'), 'price': f('Variant Price'),
                    'sku': (r.get('Variant SKU') or '').strip(),
                    'qty': (int(r['Variant Inventory Qty'])
                            if str(r.get('Variant Inventory Qty') or '').strip().lstrip('-').isdigit()
                            else None),
                    'tags': r.get('Tags') or '',
                    'bc': (r.get('Variant Barcode') or '').strip().lstrip("'")}
    # A cost repeated to the cent across three or more cards from the same source
    # is a lot average, not a purchase price — an even split over a Whatnot lot or
    # a rip. Margin computed against it is arithmetic about itself. Detected from
    # the data rather than guessed from the SKU prefix, because most Whatnot costs
    # ARE real (65 distinct across 78 cards) and only a handful are splits.
    _pairs = {}
    for p in prods.values():
        k = ((p.get('sku') or '').split('-')[0], round(p['cost'], 2))
        _pairs[k] = _pairs.get(k, 0) + 1
    for p in prods.values():
        p['alloc'] = _pairs.get(((p.get('sku') or '').split('-')[0],
                                 round(p['cost'], 2)), 0) >= 3

    active = {h: p for h, p in prods.items() if p['status'] == 'active'}

    first = st.get('first_seen', {})
    for h in active:
        first.setdefault(h, str(today))

    stale = []
    for h, p in active.items():
        seen_on = first.get(h)
        if not seen_on:
            continue
        days = (today - date.fromisoformat(seen_on)).days
        if days >= STALE_DAYS:
            stale.append((days, p))
    if stale:
        sections.append(Section(
            f'Sitting {STALE_DAYS}+ days', tone='warn',
            subtitle=plural(len(stale), 'listing'),
            cols=[('Age', 'r'), ('Price', 'r'), ('Barcode', 'l'), ('Card', 'l')],
            rows=[[f"{days}d", money(p['price']), p['bc'] or '--', p['t'][:46]]
                  for days, p in sorted(stale, key=lambda x: -x[0])[:12]],
            footnote='Your own rule: 90 days with no watchers, then unlist and demote to a bin.'))

    # ---- needs comping --------------------------------------------------------
    # Not a market check. These are cards whose own numbers disagree with each
    # other, which is the best signal available without real sold data.
    sup = _suppressed()
    skipped = sum(1 for p in active.values() if not judgeable(p, sup))
    flags = []
    for h, p in active.items():
        if not judgeable(p, sup):
            continue
        be = break_even(p['cost'])
        if net(p['price']) < p['cost']:
            flags.append(('under break-even', 'bad', p, be))
        elif p['price'] >= p['cost'] * OVERPRICED_X:
            flags.append((f'listed {p["price"]/p["cost"]:.1f}x cost', 'warn', p, be))

    if flags:
        shown = sorted(flags, key=lambda x: -x[2]['price'])[:12]
        more = len(flags) - len(shown)
        sections.append(Section(
            'Needs comping', tone='warn',
            subtitle=f"{plural(len(flags), 'card')} whose numbers disagree with each other",
            cols=[('Listed', 'r'), ('Cost', 'r'), ('Break-even', 'r'),
                  ('Why', 'l'), ('Card', 'l')],
            rows=[[money(p['price']), money(p['cost']), money(be), (why, tone), p['t'][:44]]
                  for why, tone, p, be in shown],
            footnote=(('and %d more. ' % more if more > 0 else '') +
                      'No automated source for sold prices exists for this inventory — '
                      'these are the ones to check by hand, not a market verdict. ' +
                      ('%d card(s) excluded: personal collection, rip-allocated cost, '
                       'or already decided.' % skipped if skipped else ''))))

    _append_health_checks(sections, active)
    _append_grade_scan(sections)
    _append_ig_week(sections)
    _append_market_audit(sections, active)
    _append_comp_queue(sections, active)
    _append_zero_stock(sections, active, prods)
    _append_new_arrivals(sections, active, first)
    _append_price_drift(sections)
    _append_ebay_audit(sections)
    _append_ebay_market(sections)
    _append_shipping_policy(sections)

    if age >= 3:
        sections.append(Section(
            'Stale export', tone='bad', text_prefix='!!',
            rows=[], empty=f"The Shopify export is {age} days old — costs and prices "
                           f"above may not match what is live."))

    st['last_run'] = str(today)
    st['sales_seen'] = sorted(seen)
    st['first_seen'] = first
    save_state(st)
    return title, meta, sections, _stats(new_sales, gross, realised, overdue)


def _append_ig_week(sections):
    """This week's Instagram rotation, staged by ig-wednesday.py.

    Direct sale carries no marketplace fee, so these prices are deliberately not
    the eBay asks — the two channels are priced independently. Cards marked *
    cannot be sold at a profit on eBay at market at all; dropping the 13.25% is
    the only thing that makes them work."""
    try:
        wk = json.load(open(os.path.join(HERE, 'ig-this-week.json')))
    except Exception:
        return
    picks = wk.get('picks') or []
    if not picks:
        return
    losses = [p for p in picks if p.get('profit', 0) < 0]
    rows = [[money(p['post_at']), money(p['ebay']),
             f"${p['comp_lo']:.0f}-{p['comp_hi']:.0f}",
             (money(p['profit']), 'bad' if p.get('profit', 0) < 0 else None),
             p['title'][:44]] for p in picks]
    rows = [[a, b, c, (d[0], d[1]) if d[1] else d[0], e] for a, b, c, d, e in rows]
    pool, unc = wk.get('pool', 0), wk.get('uncomped', 0)
    weeks = pool / len(picks) if picks else 0
    sections.append(Section(
        'Instagram this Wednesday', tone='info',
        subtitle=f"{plural(len(picks), 'card')} to post",
        cols=[('Post at', 'r'), ('eBay ask', 'r'), ('Comp', 'l'), ('P/L', 'r'), ('Card', 'l')],
        rows=rows,
        footnote=(f"Priced at the comp median, not the top — the goal is movement. "
                  + (f"{len(losses)} sell below cost, ${sum(-p['profit'] for p in losses):,.2f} "
                     f"accepted deliberately to return the cash. " if losses else "")
                  + f"Images in reports/ig-cards (Desktop -> DTP Instagram). "
                  f"Pool {pool}, ~{weeks:.1f} weeks before a card repeats. "
                  f"{unc} sat out with no usable comp — comping those widens the rotation.")))


def _append_market_audit(sections, active):
    """Ask vs comp vs break-even, across the whole book, every morning.

    This exists because every systemic pricing problem to date surfaced by
    accident, while doing something else. Nothing ran against the full portfolio
    on its own. Now something does.

    Two buckets, and the first is the one that matters. UNDERWATER AT MARKET
    means the top of the comp range is below break-even: the card cannot be sold
    at a profit at any price a buyer will pay, so repricing it is not the fix and
    the money is already gone. OVER MARKET means it will sell, just not at this
    ask.

    Caveat carried in the footnote on purpose: comp-data.json was gathered by
    hand on 27 Aug and its matching is unreliable for numbered parallels — it
    picks up base-card sales. Treat the direction as real and the magnitude as
    a prompt to re-comp, never as a verdict."""
    # comp-verified.json is machine-gathered with explicit grade/parallel/print-run
    # filtering and overrides the 27 August hand-built set, which matches base
    # cards against numbered parallels. Kept as two files on purpose so a bad
    # harvest can be dropped without losing the old work.
    comps = {}
    for f in ('comp-data.json', 'comp-verified.json'):
        try:
            for c in json.load(open(os.path.join(HERE, f))):
                if c.get('lo') not in (None, ''):
                    comps[c['title']] = c
        except Exception:
            pass
    if not comps:
        return
    sup = _suppressed()
    dead, over = [], []
    for h, p in active.items():
        c = comps.get(p['t'])
        if not c or c.get('lo') in (None, '') or not judgeable(p, sup):
            continue
        try:
            lo, hi = float(c['lo']), float(c['hi'])
        except (TypeError, ValueError):
            continue
        be = break_even(p['cost'])
        if be is None:
            continue
        if hi < be:
            dead.append((be - hi, p, lo, hi, be))
        elif p['price'] > hi:
            over.append((p['price'] - hi, p, lo, hi, be))
    if dead:
        sections.append(Section(
            'Underwater at market', tone='bad', text_prefix='!!',
            subtitle=f"{plural(len(dead), 'card')} whose best comp is below break-even",
            cols=[('Ask', 'r'), ('Break-even', 'r'), ('Comp', 'l'), ('Short', 'r'), ('Card', 'l')],
            rows=[[money(p['price']), money(be), f'${lo:.0f}-{hi:.0f}', money(g), p['t'][:40]]
                  for g, p, lo, hi, be in sorted(dead, key=lambda x: -x[0])[:10]],
            footnote='Repricing does not fix these — the market will not reach cost. '
                     'Comps are the hand-built 27 Aug set and match badly on numbered '
                     'parallels, so re-comp before acting on any single line.'))
    if over:
        sections.append(Section(
            'Priced over market', tone='warn',
            subtitle=f"{plural(len(over), 'card')} sellable, but not at this ask",
            cols=[('Ask', 'r'), ('Comp', 'l'), ('Over by', 'r'), ('Card', 'l')],
            rows=[[money(p['price']), f'${lo:.0f}-{hi:.0f}', money(g), p['t'][:44]]
                  for g, p, lo, hi, be in sorted(over, key=lambda x: -x[0])[:10]],
            footnote='These will sell once the ask meets the comp range.'))


PERSONAL_PRICE = 9000.0     # legacy fallback; the marker is now the `Personal` tag


HELD_TAGS = ('Personal', 'At PSA')


def _has_tag(p, tag):
    return tag in [t.strip() for t in (p.get('tags') or '').split(',')]


def is_personal(p):
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
    tags = [t.strip() for t in (p.get('tags') or '').split(',')]
    if any(t in HELD_TAGS for t in tags):
        return True
    try:
        return float(p.get('price') or 0) >= 9000
    except (TypeError, ValueError):
        return False
SUPPRESS = os.path.join(HERE, 'suppress.json')


def _suppressed():
    """Cards Craig has already decided about, keyed by SKU.

    A briefing that flags a deliberate decision every morning trains you to skim
    past it, and then it is worth nothing on the day it says something new."""
    try:
        return {e['sku']: e.get('reason', 'acknowledged')
                for e in json.load(open(SUPPRESS))}
    except Exception:
        return {}


def judgeable(p, sup):
    """Whether a cost-versus-price judgement on this card means anything.

    Three classes where it does not:
      · personal collection — priced at $9,999 so it cannot sell, not a mispricing
      · Boxes- SKUs — cost is allocated in proportion to list price, so 'listed
        3x cost' is arithmetic about itself. See the rip-allocation note.
      · anything in suppress.json — already decided, deliberately
    """
    if is_personal(p) or p['cost'] <= 0 or p['price'] <= 0:
        return False
    if (p.get('sku') or '').split('-')[0] == 'Boxes':
        return False
    if p.get('alloc'):          # cost is a lot average — see where it is set
        return False
    return (p.get('sku') or '') not in sup


DEADLINES = os.path.join(HERE, 'deadlines.json')
DEADLINE_HORIZON = 45      # far enough out to act, near enough to still matter


def _append_deadlines(sections):
    """Dated obligations with money on them.

    These are the losses that happen by silence — a return window that closes, a
    claim that expires. Nothing else in this briefing watches a calendar, so
    without this the only thing standing between Craig and the loss is memory.

    Entries live in deadlines.json; set done:true rather than deleting, so the
    record of what was handled survives. `estimated:true` marks a date that was
    inferred rather than confirmed, and says so in the row."""
    try:
        items = [d for d in json.load(open(DEADLINES)) if not d.get('done')]
    except Exception:
        return
    rows, worst = [], None
    for d in sorted(items, key=lambda x: x['due']):
        try:
            left = (date.fromisoformat(d['due']) - date.today()).days
        except Exception:
            continue
        if left > DEADLINE_HORIZON:
            continue
        when = 'OVERDUE' if left < 0 else ('today' if left == 0 else f'{left}d')
        tone = 'bad' if left <= 7 else ('warn' if left <= 21 else None)
        worst = min(worst, left) if worst is not None else left
        rows.append([(when, tone) if tone else when,
                     money(d['amount']) if d.get('amount') else '--',
                     d['due'] + ('*' if d.get('estimated') else ''),
                     d['label'][:44]])
    if not rows:
        return
    urgent = worst is not None and worst <= 7
    kw = {'text_prefix': '!!'} if urgent else {}
    sections.append(Section(
        'Deadlines', tone='bad' if urgent else 'warn',
        subtitle=plural(len(rows), 'dated obligation'),
        cols=[('Left', 'r'), ('At stake', 'r'), ('Due', 'l'), ('What', 'l')],
        rows=rows,
        footnote='* date is estimated, not confirmed — worth checking the actual '
                 'window. Edit reports/deadlines.json; set done:true when handled.',
        **kw))


COMP_STALE_DAYS = 60      # a comp older than this is a guess again


def _append_comp_queue(sections, active):
    """Cards that cannot be priced against the market, ranked by money at stake.

    Comping needs a browser, so it can never be a cron job — which means the only
    thing keeping it moving is that it stays visible. This is that. Cards with no
    comp at all come first, then comps old enough to have drifted.

    Deliberately excludes the same classes as every other judgement here: the
    personal collection, rip-allocated costs, and anything already decided."""
    comps = {}
    for f in ('comp-data.json', 'comp-verified.json'):
        try:
            for c in json.load(open(os.path.join(HERE, f))):
                if c.get('lo') not in (None, ''):
                    comps[c['title']] = c
        except Exception:
            pass
    sup = _suppressed()
    rows = []
    for h, p in active.items():
        if not judgeable(p, sup):
            continue
        c = comps.get(p['t'])
        if c is None:
            rows.append((p['price'], 'no comp', p['t']))
            continue
        d = c.get('date')
        if d:
            try:
                age = (date.today() - date.fromisoformat(d)).days
                if age >= COMP_STALE_DAYS:
                    rows.append((p['price'], f'{age}d old', p['t']))
            except Exception:
                pass
    if not rows:
        return
    rows.sort(reverse=True)
    at_stake = sum(r[0] for r in rows)
    sections.append(Section(
        'Comp queue', tone='warn',
        subtitle=f"{plural(len(rows), 'card')} that cannot be priced against the market",
        cols=[('Ask', 'r'), ('Why', 'l'), ('Card', 'l')],
        rows=[[money(p), why, t[:46]] for p, why, t in rows[:10]],
        footnote=(f"${at_stake:,.2f} of ask with no defensible price. "
                  f"Comping needs a browser, so it only moves when someone works it: "
                  f"reports/comp-tools.py. Low-pop parallels (/25, /30) often have no "
                  f"raw sales at all — those are grade-or-hold decisions, not pricing ones.")))


def _append_zero_stock(sections, active, prods_raw):
    """Active listings with nothing behind them.

    A sold card can sit ACTIVE in Shopify with quantity 0. On 9 Sept the Cam
    Skattebo had sold two days earlier and was still staged for an Instagram
    post — advertising stock that does not exist. Anything still live on eBay in
    that state is also a double-sell waiting to happen."""
    rows = [(p['price'], p['t']) for p in prods_raw.values()
            if p['status'] == 'active' and p.get('qty') is not None
            and p['qty'] < 1 and not is_personal(p)]
    if not rows:
        return
    rows.sort(reverse=True)
    sections.append(Section(
        'Active with no stock', tone='bad', text_prefix='!!',
        subtitle=f"{plural(len(rows), 'listing')} live with zero inventory",
        cols=[('Price', 'r'), ('Card', 'l')],
        rows=[[money(p), t[:50]] for p, t in rows[:10]],
        footnote='Sold, or never stocked. Archive them — while they are active they '
                 'can still be bought, on the website and on eBay.'))



NEW_DAYS = 7               # a listing's first week is when a mistake is still cheap
DEAD_ZONE_TOP = 25.31      # where Ground Advantage finally beats the lost envelope
VERIFIED = os.path.join(HERE, 'comp-verified.json')


def _append_new_arrivals(sections, active, first):
    """Every new listing's first week, checked before the card sells.

    This is the gap that has cost the most money. Every audit in this briefing is
    catalogue-wide and runs on what is already listed; nothing looks at a card
    at the moment it ARRIVES. So the same failure keeps recurring:

      three Josh Allens went live BELOW COST on 8 Sept because they landed after
      the big reprice pass and nobody re-floored them;
      the Drew Allar sold 7 Sept for $199.99 with no cost recorded, so its P/L is
      permanently unknowable;
      the Emeka Egbuka Red Lava sold 9 Sept at $42.75 against a $62 cost -- a
      $31 loss -- because it was one of a handful of listings with no minimum
      offer set.

    Each was found weeks later, by accident, after the money was gone. A card
    listed wrong is cheap to fix on day one and expensive on day thirty."""
    try:
        comped = {e.get('title') for e in json.load(open(VERIFIED))}
    except Exception:
        comped = set()
    cutoff = str(date.today() - timedelta(days=NEW_DAYS))
    rows = []
    for h, p in active.items():
        if (first.get(h) or '') < cutoff:
            continue
        price = p['price']
        if price <= 0 or is_personal(p):
            continue
        if (p.get('sku') or '').split('-')[0] == 'Boxes' or p.get('alloc'):
            continue
        cost = p['cost']
        if cost <= 0:
            rows.append((3, price, 'no cost recorded', p['t']))
            continue
        be = break_even(cost)
        if be and price < be:
            rows.append((3, price, f'under break-even {money(be)}', p['t']))
        elif ESE_MAX_ITEM < price < DEAD_ZONE_TOP:
            # Above $19.22 the item no longer fits eBay Standard Envelope, so
            # shipping jumps $0.78 -> $6.07. Between there and $25.31 the extra
            # postage costs more than the extra price earns: $19.22 nets $15.49
            # and $25.00 nets $15.22. Price below the floor or above the top,
            # never inside.
            rows.append((2, price, 'in the $19.22-25.31 dead zone', p['t']))
        elif p['t'] not in comped:
            rows.append((1, price, 'no comp - price is a guess', p['t']))
    if not rows:
        return
    rows.sort(key=lambda r: (-r[0], -r[1]))
    worst = sum(1 for r in rows if r[0] == 3)
    sections.append(Section(
        'New this week', tone='bad' if worst else 'warn',
        text_prefix='!!' if worst else None,
        subtitle=f"{plural(len(rows), 'new listing')} with something unresolved",
        cols=[('Listed', 'r'), ('Problem', 'l'), ('Card', 'l')],
        rows=[[money(pr), (why, 'bad' if sev == 3 else None), t[:46]]
              for sev, pr, why, t in rows[:12]],
        footnote='Checked for the first %d days after a listing appears. Fixing a '
                 'price on day one costs nothing; finding it after the card sells '
                 'costs the whole margin.' % NEW_DAYS))

def _append_price_drift(sections):
    """Cards whose website price no longer matches eBay.

    eBay is the price source of truth and InfoShore is meant to copy every change
    to Shopify. On 2026-09-22 51 cards were found out of step - 47 dearer on the
    website, most frozen at their 8 Sept price - with Price Sync switched on.
    Nobody noticed for two weeks. Reads price-drift.json from price-drift.py."""
    try:
        d = json.load(open(os.path.join(HERE, 'price-drift.json')))
    except Exception:
        return
    if d.get('ran') != str(date.today()):
        sections.append(Section(
            'Website vs eBay price check did not run', tone='warn', rows=[],
            empty=(f"Last real check: {d.get('ran') or 'unknown'}. Website prices "
                   f"were not compared with eBay today - unknown, not clean.")))
        return
    rows = d.get('drift') or []
    if not rows:
        return
    dearer = sum(1 for r in rows if r['site'] > r['ebay'])
    sections.append(Section(
        'Website prices out of step with eBay', tone='warn',
        subtitle=(f"{plural(len(rows), 'card')} of {d.get('checked', '?')} checked - "
                  f"{dearer} dearer on the website, {len(rows) - dearer} cheaper"),
        cols=[('eBay', 'r'), ('Website', 'r'), ('Card', 'l')],
        rows=[[money(r['ebay']), money(r['site']), r['title'][:44]] for r in rows[:15]],
        footnote=("eBay is the source of truth, so the fix is to bring the website into "
                  "line - ask Claude to set these Shopify prices to eBay. Re-saving the eBay "
                  "listing (Revise, no change) also pushes the price down. If this keeps "
                  "happening, InfoShore support should be told which edits it misses.")))


def _append_ebay_audit(sections):
    """Listing faults that cost sales without ever showing up as a problem.

    Written after the Josh Allen Glass Mosaic: $150, a print line and back damage,
    an EMPTY condition field, and a description of pure marketing fluff. Three
    separate buyers had to message and ask what was wrong with it before one
    offered $130 and walked. Nothing in this briefing would have caught that.

    Reads ebay-audit.json, produced headlessly by ebay-audit.py on the eBay Browse
    API — no browser, so it runs in the 07:00 job like everything else here."""
    try:
        d = json.load(open(os.path.join(HERE, 'ebay-audit.json')))
    except Exception:
        return
    # A result from an earlier day says nothing about today. The Browse quota used
    # to run out mid-morning — every later call came back 429, the fault list came
    # out empty, and this section simply vanished. That silence read exactly like
    # "nothing wrong with your listings", which is the opposite of what it meant.
    if d.get('ran') != str(date.today()):
        sections.append(Section(
            'eBay listing audit did not run', tone='warn', rows=[],
            empty=(f"Last real audit: {d.get('ran') or 'unknown'}. The Browse API "
                   f"refused today's calls (usually the daily quota). No listing "
                   f"faults are shown below because none were checked — unknown, "
                   f"not clean.")))
        return
    rows = d.get('faults') or []
    if not rows:
        return
    blank = [r for r in rows if 'no condition notes' in r['faults']]
    at_stake = sum(r['price'] for r in blank)
    sections.append(Section(
        'Listing faults on eBay', tone='warn',
        subtitle=f"{plural(len(rows), 'listing')} of {d.get('checked', '?')} with something wrong",
        cols=[('Price', 'r'), ('Problem', 'l'), ('Card', 'l')],
        rows=[[money(r['price']), ', '.join(r['faults'])[:44], r['title'][:38]]
              for r in rows[:10]],
        footnote=(f"{len(blank)} have a BLANK condition field, {money(at_stake)} of listed "
                  f"value. An ungraded card with no condition note invites the "
                  f"\"what's wrong with it\" message, a lowball, or a return — the Glass "
                  f"Mosaic drew three such messages before an offer that walked. "
                  f"Fix the condition notes first; boilerplate descriptions matter less.")))


def _append_ebay_market(sections):
    """Where each listing sits against the people selling the same card TODAY.

    Asking prices, not sold prices — the Golden's actives ran $615-700 against
    verified sold comps of $525-629, so this is competitive position, not value.
    The yardstick for value is still comp-verified.json.

    Pulled headlessly from the Browse API by ebay-market.py, and filtered through
    the same matching rules as comp-tools.py. Without that filter the check is
    worse than useless: raw keyword search put the Golden against listings from
    $20 to $30,000 and McMillan's median at $2."""
    try:
        d = json.load(open(os.path.join(HERE, 'ebay-market.json')))
    except Exception:
        return
    if d.get('ran') != str(date.today()):
        sections.append(Section(
            'Competitor sweep did not run', tone='warn', rows=[],
            empty=(f"Last real sweep: {d.get('ran') or 'unknown'}. The Browse API "
                   f"refused today's searches (usually the daily quota), so nothing "
                   f"was compared against the live board today.")))
        return
    rows = d.get('flagged') or []
    if not rows:
        return
    top = [r for r in rows if r['flag'] == 'highest on the board']
    sections.append(Section(
        'Against live competitors', tone='warn',
        subtitle=f"{plural(len(rows), 'listing')} out of step with the board",
        cols=[('Yours', 'r'), ('Others asking', 'l'), ('', 'l'), ('Card', 'l')],
        rows=[[money(r['mine']), f"${r['lo']:.0f}-{r['hi']:.0f} (med ${r['median']:.0f})",
               r['flag'], r['title'][:34]] for r in rows[:10]],
        footnote=(f"{len(top)} are the highest ask on the board — the last card anyone "
                  f"buys. These are ASKING prices, not sales: people ask what they hope "
                  f"for. Use comp-verified.json for value and this for position.")))


def _dead_zone_top():
    """The price above which Ground Advantage finally beats the ESE cap.

    Anything between the cap and this number pays the $6.07 label without
    collecting enough extra to cover it, so it nets less than the cap does."""
    base = net(ESE_MAX_ITEM)
    x = ESE_MAX_ITEM + 0.01
    while x < 60:
        if net(x) >= base:
            return round(x, 2)
        x = round(x + 0.01, 2)
    return ESE_MAX_ITEM


def _norm(title):
    """Titles for duplicate-matching, punctuation and case removed.

    The 1 Sep double-import wrote card numbers with a space where the first
    pass used a hyphen — '#PK 10' against '#PK-10'. Different title, different
    handle, so Shopify made a second product instead of matching the first."""
    return re.sub(r'[^a-z0-9]', '', title.lower())


def _append_shipping_policy(sections):
    """eBay listings sitting on the wrong shipping policy for their price.

    The store runs two policies - $4.99 Ground Advantage over $20, $1.36 eBay
    Standard Envelope under it - but a NEW eBay listing always defaults to
    Ground Advantage. So every batch listed re-creates the gap silently. On the
    same day the split was set up (2026-09-21) 122 cheap cards had already
    drifted back onto $4.99; on a $1.99 card that is $6.98 to the buyer against
    $3.35, and it simply does not sell.

    The two faults are not equally bad and are reported apart. A DEAR card on ESE
    is the one that matters: ESE has a hard $20 declared-value cap and no
    insurance, so it is outside eBay's terms and a loss cannot be recovered.

    Reads ebay-shipping-check.json from ebay-shipping-check.py."""
    try:
        d = json.load(open(os.path.join(HERE, 'ebay-shipping-check.json')))
    except Exception:
        return
    # Same trap as the listing audit: a stale file reads as "nothing wrong".
    if d.get('ran') != str(date.today()):
        sections.append(Section(
            'Shipping-policy check did not run', tone='warn', rows=[],
            empty=(f"Last real check: {d.get('ran') or 'unknown'}. Nothing below "
                   f"was verified today - unknown, not clean.")))
        return
    dear = d.get('dear_on_ese') or []
    cheap = d.get('cheap_on_ga') or []

    if dear:
        sections.append(Section(
            'OVER $20 on eBay Standard Envelope', tone='bad', text_prefix='!!',
            subtitle=(f"{plural(len(dear), 'listing')} above ESE's $20 declared-value "
                      f"cap - no insurance, outside eBay's terms, a loss is "
                      f"unrecoverable. Move these to Shipping (DTP) today."),
            cols=[('Price', 'r'), ('Ship', 'r'), ('Card', 'l')],
            rows=[[money(r['price']), money(r['ship']), r['title'][:52]] for r in dear[:15]],
            footnote=(f"...and {len(dear) - 15} more" if len(dear) > 15 else None)))

    if cheap:
        sections.append(Section(
            'Cheap cards paying $4.99 shipping', tone='warn', text_prefix='!!',
            subtitle=(f"{plural(len(cheap), 'listing')} under $20 still on Ground "
                      f"Advantage - should be ESE at $1.36. New listings default to "
                      f"Ground Advantage, so this refills after every batch. "
                      f"NOTE: the Browse API lags a few hours after a bulk edit - "
                      f"if you have just swept, check a listing page before believing this."),
            cols=[('Price', 'r'), ('Ship', 'r'), ('Card', 'l')],
            rows=[[money(r['price']), money(r['ship']), r['title'][:52]] for r in cheap[:12]],
            footnote=(f"...and {len(cheap) - 12} more. Seller Hub -> filter price "
                      f"under $20 -> bulk edit -> Shipping (DTP)- ESE."
                      if len(cheap) > 12 else None)))


def _append_health_checks(sections, active):
    """Catalogue hygiene. Every one of these was found by hand on 1-2 Sep and
    every one of them recurs after an import, so it belongs in the briefing
    rather than in someone's memory."""

    # Held cards are deliberately costless, priceless and duplicated, so every
    # check below skips them. A `Personal` card is an owner draw with no COGS by
    # definition; flagging it as "no cost recorded" is a warning that can never be
    # cleared, and the two Josh Allen Blue Surges — genuinely two copies, both
    # moved to the personal collection on 15 Sept — are not a catalogue fault
    # either. `is_personal` already gates posting and repricing; these three
    # checks were simply never wired to it.
    sellable = {h: p for h, p in active.items() if not is_personal(p)}

    # A hobby-box pull really did cost $0. Blank and zero are both `cost <= 0`
    # here, so without a marker the pulls sit in this list forever — entering the
    # true cost of 0 does not clear it. The `Zero-cost` tag says "this has been
    # accounted for", the same way `Personal` says "this is not for sale".
    zero_cost = [p for p in sellable.values() if _has_tag(p, 'Zero-cost')]
    no_cost = sorted((p for p in sellable.values()
                      if p['cost'] <= 0 and not _has_tag(p, 'Zero-cost')),
                     key=lambda p: -p['price'])
    if no_cost:
        sections.append(Section(
            'No cost recorded', tone='warn', text_prefix='!!',
            subtitle=(f"{plural(len(no_cost), 'listing')} — margin and break-even "
                      f"cannot be computed for these"),
            cols=[('Price', 'r'), ('Card', 'l')],
            rows=[[money(p['price']), p['t'][:56]] for p in no_cost[:15]],
            footnote=(f"...and {len(no_cost) - 15} more" if len(no_cost) > 15 else None)))

    if zero_cost:
        sections.append(Section(
            'Zero-cost stock', tone='muted',
            subtitle=(f"{plural(len(zero_cost), 'listing')} pulled from a box — "
                      f"$0 basis, so any sale is 100% margin"),
            cols=[('Price', 'r'), ('Card', 'l')],
            rows=[[money(p['price']), p['t'][:56]] for p in zero_cost[:10]],
            footnote='Real, but it flatters the margin average — read it separately.'))

    free = sorted((p for p in sellable.values() if p['price'] <= 0),
                  key=lambda p: -p['cost'])
    if free:
        sections.append(Section(
            'Listed at $0.00', tone='bad', text_prefix='!!',
            subtitle=(f"{plural(len(free), 'listing')} live on the storefront "
                      f"with no price"),
            cols=[('Cost', 'r'), ('Card', 'l')],
            rows=[[(money(p['cost']), 'bad'), p['t'][:56]] for p in free[:15]],
            footnote='Set these to DRAFT if they are not for sale.'))

    by_title = {}
    for p in sellable.values():
        by_title.setdefault(_norm(p['t']), []).append(p)
    dupes = [v for v in by_title.values() if len(v) > 1]
    if dupes:
        rows = []
        for grp in sorted(dupes, key=lambda g: -g[0]['price'])[:12]:
            rows.append([str(len(grp)), money(grp[0]['price']), grp[0]['t'][:50]])
        sections.append(Section(
            'Duplicate titles', tone='bad', text_prefix='!!',
            subtitle=(f"{plural(len(dupes), 'card')} listed more than once — "
                      f"check before deleting, you do own some cards twice"),
            cols=[('#', 'r'), ('Price', 'r'), ('Card', 'l')], rows=rows))

    top = _dead_zone_top()
    dead = sorted((p for p in active.values() if ESE_MAX_ITEM < p['price'] < top),
                  key=lambda p: p['price'])
    if dead:
        sections.append(Section(
            'In the shipping dead zone', tone='warn',
            subtitle=(f"{plural(len(dead), 'listing')} priced between "
                      f"{money(ESE_MAX_ITEM)} and {money(top)}"),
            cols=[('Price', 'r'), ('Nets', 'r'), ('Card', 'l')],
            rows=[[money(p['price']), money(net(p['price'])), p['t'][:48]] for p in dead[:12]],
            footnote=(f"{money(ESE_MAX_ITEM)} nets {money(net(ESE_MAX_ITEM))} on an "
                      f"envelope. These pay for a {money(GA)} label and net less. "
                      f"Drop to the cap or push above {money(top)}.")))


def _append_grade_scan(sections):
    """Fold in the latest raw-to-graded scan, if there is a recent one.

    Read from a file the scanner wrote rather than running it here. The scan
    makes a lot of eBay calls and can be slow or fail; the briefing must not
    wait on it or die with it. No recent scan simply means no section."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'grade_scan', os.path.join(HERE, 'grade-scan.py'))
        gs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gs)
        latest = gs.load_latest()
    except Exception:
        return
    if not latest:
        return

    picks = latest.get('picks') or []
    if picks:
        sections.append(Section(
            'Worth buying to grade', tone='good',
            subtitle=('%d candidate%s, ranked by expected value%s'
                      % (len(picks), '' if len(picks) == 1 else 's',
                         '' if latest.get('insights') else ' — comps are ASKING prices')),
            cols=[('EV', 'r'), ('ROI', 'r'), ('Buy', 'r'), ('PSA 10', 'r'),
                  ('Gem', 'r'), ('If it 9s', 'r'), ('Card', 'l')],
            rows=[[('{:+,.2f}'.format(p['ev_profit']), 'good'),
                   '{:.0f}%'.format(p['ev_roi'] * 100),
                   '${:,.2f}'.format(p['acquire']),
                   '${:,.2f}'.format(p['p10']),
                   '{:.1f}%'.format(p['gem'] * 100),
                   ('{:+,.2f}'.format(p['downside']),
                    'bad' if p['downside'] < 0 else None),
                   p['title'][:46]] for p in picks[:8]],
            footnote=('Listings move fast — verify these are still live before '
                      'acting. Scanned %s.' % latest.get('ran', '?'))))

    unjudged = latest.get('unjudged') or []
    if unjudged:
        sections.append(Section(
            'Grade scan — needs a gem rate', tone='muted',
            subtitle='wide spreads, no population on file, so not judged',
            cols=[('Spread', 'r'), ('Buy', 'r'), ('Card', 'l')],
            rows=[['${:,.2f}'.format(u['spread']), '${:,.2f}'.format(u['acquire']),
                   u['title'][:52]] for u in unjudged[:5]],
            footnote='Look them up on gemrate.com, then: grade-scan.py --gem ...'))


def _stats(new_sales, gross, realised, overdue):
    """The three numbers worth seeing before the email is even opened."""
    out = [('sold', str(len(new_sales)), None),
           ('gross', money(gross), None)]
    if realised is not None:
        out.append(('realised', signed(realised), 'good' if realised >= 0 else 'bad'))
    elif overdue:
        out.append(('overdue', str(len(overdue)), 'bad'))
    return out


def send(subject, text, html):
    """POST the briefing to the site's Worker, which emails it. The key lives in
    ~/.dtp-briefing-key, outside the repo — a secret in a tracked file is a
    secret you have published.

    Both parts go up. The Worker sends them as multipart/alternative so a client
    that will not render HTML still gets a readable briefing rather than a wall
    of markup."""
    import urllib.request, urllib.error
    kp = os.path.expanduser('~/.dtp-briefing-key')
    if not os.path.exists(kp):
        print('[no ~/.dtp-briefing-key — skipping email]', file=sys.stderr)
        return
    key = open(kp).read().strip()
    body = json.dumps({'subject': subject, 'text': text, 'html': html})
    req = urllib.request.Request(
        'https://duxburytradingpost.com/api/briefing',
        data=body.encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8', 'X-DTP-Key': key,
                 # Cloudflare's bot rules reject urllib's default agent with a
                 # 1010 before the request ever reaches the Worker.
                 'User-Agent': 'DuxburyTradingPost-Briefing/1.0 (+https://duxburytradingpost.com)'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f'[emailed: HTTP {r.status}]', file=sys.stderr)
    except urllib.error.HTTPError as e:
        print(f'[email failed: HTTP {e.code} {e.read().decode()[:120]}]', file=sys.stderr)
    except Exception as e:
        print(f'[email failed: {e}]', file=sys.stderr)


def _already_sent_today():
    """Has today's briefing already gone out?

    The schedule cannot assume the Mac is awake. It sleeps overnight, so a job
    pinned to 07:00 simply never fires — which is exactly what happened on
    10 Sept, the morning after the timezone was corrected FROM 10:00 (when the
    machine happened to be awake) TO 07:00 (when it is not). So the job now polls
    while awake and decides for itself whether today is done."""
    try:
        return json.load(open(STATE)).get('last_emailed') == str(date.today())
    except Exception:
        return False


def _mark_sent_today():
    try:
        st = json.load(open(STATE))
    except Exception:
        st = {}
    st['last_emailed'] = str(date.today())
    json.dump(st, open(STATE, 'w'), indent=1)


if __name__ == '__main__':
    # --once-daily: run only after the send hour, and only if today has not gone
    # out yet. Lets launchd poll every half hour without spamming.
    if '--once-daily' in sys.argv:
        if _already_sent_today():
            sys.exit(0)
        if datetime.now().hour < 7:
            sys.exit(0)

    title, meta, sections, stats = build()
    text = render_text(title, meta, sections)
    print(text)

    if '--html' in sys.argv:
        # Written next to the script so it can be opened in a browser and
        # checked without sending anything.
        out = os.path.join(HERE, 'briefing-preview.html')
        with open(out, 'w') as fh:
            fh.write(render_html(title, meta, sections, stats))
        print(f'[preview written to {out}]', file=sys.stderr)

    # Email first. Saving a copy is a convenience; delivering the briefing is
    # the whole job. The original order had the write first, and when launchd
    # hit PermissionError on ~/Desktop the process died on that line and the
    # briefing was never sent — a failed nicety silently cancelled the point.
    if '--no-email' not in sys.argv:
        send(title, text, render_html(title, meta, sections, stats))
        _mark_sent_today()

    try:
        with open(os.path.join(HERE, 'DTP-daily-briefing.txt'), 'w') as fh:
            fh.write(text + "\n")
    except OSError as e:
        print(f'[could not save a copy: {e}]', file=sys.stderr)
