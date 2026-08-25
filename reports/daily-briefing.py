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
STALE_DAYS   = 45                # the release-valve window, minus a little warning
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
        if not m:
            continue
        last = m[-1]
        try:
            eta = date(today.year, MON[last[0]], int(last[1]))
        except Exception:
            continue
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

    # ---- the catalogue side ---------------------------------------------------
    export = newest_export()
    if not export:
        sections.append(Section(
            'Catalogue checks skipped', tone='muted',
            rows=[], empty='No Shopify export found — export from Shopify to restore '
                           'the comping queue.'))
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
                    'bc': (r.get('Variant Barcode') or '').strip().lstrip("'")}
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
    flags = []
    for h, p in active.items():
        if p['cost'] <= 0 or p['price'] <= 0:
            continue
        be = break_even(p['cost'])
        if net(p['price']) < p['cost']:
            flags.append(('under break-even', 'bad', p, be))
        elif p['price'] >= p['cost'] * OVERPRICED_X:
            flags.append((f'listed {p["price"]/p["cost"]:.1f}x cost', 'warn', p, be))
    dead = [p for p in active.values() if ESE_MAX_ITEM < p['price'] <= 26]

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
                      'these are the ones to check by hand, not a market verdict.')))

    if dead:
        sections.append(Section(
            f'In the {money(ESE_MAX_ITEM)}–$26 dead zone', tone='muted',
            subtitle=plural(len(dead), 'listing'),
            rows=[], empty=(f"Over the ESE cap, so the label jumps {money(GA - ESE)}. "
                            f"{money(ESE_MAX_ITEM)} nets more than $22 does.")))

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


if __name__ == '__main__':
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

    try:
        with open(os.path.join(HERE, 'DTP-daily-briefing.txt'), 'w') as fh:
            fh.write(text + "\n")
    except OSError as e:
        print(f'[could not save a copy: {e}]', file=sys.stderr)
