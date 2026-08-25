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
import csv, json, glob, os, re, sys, subprocess
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


def build():
    today = date.today()
    st = load_state()
    seen = set(st.get('sales_seen', []))
    out = []
    w = out.append

    w(f"DUXBURY TRADING POST — morning briefing   {today}")
    if st.get('last_run'):
        w(f"since {st['last_run']}")
    w("")

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

    if new_sales:
        tot = sum(s[2] for s in new_sales)
        known = [s[3] for s in new_sales if s[3] is not None]
        w(f"── SOLD — {len(new_sales)} cards, ${tot:,.2f} gross")
        for d, card, sold, pl in sorted(new_sales, key=lambda x: -x[2]):
            tag = f"{pl:+8.2f}" if pl is not None else "       ?"
            w(f"   {tag}   ${sold:8.2f}  {card[:56]}")
        if known:
            w(f"   {'':8}   realised P/L on the {len(known)} with a cost basis: {sum(known):+,.2f}")
    else:
        w("── SOLD — nothing since the last run")
    w("")

    if below:
        w(f"!! SOLD BELOW BREAK-EVEN — {len(below)}")
        for card, sold, basis, pl in below:
            w(f"   {pl:+8.2f}   sold ${sold:7.2f} against ${basis:7.2f} cost   {card[:48]}")
        w("")

    # ---- arrivals due ---------------------------------------------------------
    log = sheet_rows('Purchase log')[1:]
    due, overdue = [], []
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
        MON = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,
               'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
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
        w(f"!! OVERDUE ARRIVALS — {len(overdue)}")
        for i, card, paid, eta, days in sorted(overdue, key=lambda x: -x[4]):
            w(f"   {days:3}d late  ${paid:8,.2f}  row {i:3}  {card[:50]}")
        w("")
    if due:
        w(f"── DUE TODAY — {len(due)}")
        for i, card, paid in due:
            w(f"   ${paid:8,.2f}  row {i:3}  {card[:56]}")
        w("")

    # ---- the catalogue side ---------------------------------------------------
    export = newest_export()
    if not export:
        w("── no Shopify export on the Desktop — catalogue checks skipped")
        st['last_run'] = str(today)
        st['sales_seen'] = sorted(seen)
        save_state(st)
        return "\n".join(out)

    age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(export))).days
    rows = list(csv.DictReader(open(export)))
    prods = {}
    for r in rows:
        h = (r.get('Handle') or '').strip()
        t = (r.get('Title') or '').strip()
        if not h or not t or h in prods:
            continue
        def f(k):
            try: return float(r.get(k) or 0)
            except: return 0.0
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
        w(f"── SITTING {STALE_DAYS}+ DAYS — {len(stale)}")
        for days, p in sorted(stale, key=lambda x: -x[0])[:12]:
            w(f"   {days:3}d  ${p['price']:8.2f}  {p['bc'] or '--':10} {p['t'][:46]}")
        w("   your own rule: 90 days with no watchers -> unlist and demote to a bin")
        w("")

    # ---- needs comping --------------------------------------------------------
    # Not a market check. These are cards whose own numbers disagree with each
    # other, which is the best signal available without real sold data.
    flags = []
    for h, p in active.items():
        if p['cost'] <= 0 or p['price'] <= 0:
            continue
        be = break_even(p['cost'])
        if net(p['price']) < p['cost']:
            flags.append(('under break-even', p, be))
        elif p['price'] >= p['cost'] * OVERPRICED_X:
            flags.append((f'listed {p["price"]/p["cost"]:.1f}x cost', p, be))
    dead = [p for p in active.values() if ESE_MAX_ITEM < p['price'] <= 26]

    if flags:
        w(f"── NEEDS COMPING — {len(flags)} cards whose numbers disagree")
        w("   (no automated source for sold prices exists for this inventory —")
        w("    these are the ones to check by hand, not a market verdict)")
        for why, p, be in sorted(flags, key=lambda x: -x[1]['price'])[:12]:
            w(f"   ${p['price']:8.2f}  cost ${p['cost']:7.2f}  BE ${be:7.2f}  {why:18} {p['t'][:34]}")
        w("")
    if dead:
        w(f"── IN THE $19.22-$26 DEAD ZONE — {len(dead)}")
        w(f"   over the ESE cap, so the label jumps ${GA-ESE:.2f}. ${ESE_MAX_ITEM:.2f} nets more than $22 does.")
        w("")

    if age >= 3:
        w(f"!! the Shopify export is {age} days old — costs and prices above may be stale")
        w("")

    st['last_run'] = str(today)
    st['sales_seen'] = sorted(seen)
    st['first_seen'] = first
    save_state(st)
    return "\n".join(out)


def send(text):
    """POST the briefing to the site's Worker, which emails it. The key lives in
    ~/.dtp-briefing-key, outside the repo — a secret in a tracked file is a
    secret you have published."""
    import urllib.request, urllib.error
    kp = os.path.expanduser('~/.dtp-briefing-key')
    if not os.path.exists(kp):
        print('[no ~/.dtp-briefing-key — skipping email]', file=sys.stderr)
        return
    key = open(kp).read().strip()
    req = urllib.request.Request(
        'https://duxburytradingpost.com/api/briefing',
        data=text.encode('utf-8'),
        headers={'Content-Type': 'text/plain; charset=utf-8', 'X-DTP-Key': key,
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
    text = build()
    print(text)

    # Email first. Saving a copy is a convenience; delivering the briefing is
    # the whole job. The original order had the write first, and when launchd
    # hit PermissionError on ~/Desktop the process died on that line and the
    # briefing was never sent — a failed nicety silently cancelled the point.
    if '--no-email' not in sys.argv:
        send(text)

    try:
        with open(os.path.join(HERE, 'DTP-daily-briefing.txt'), 'w') as fh:
            fh.write(text + "\n")
    except OSError as e:
        print(f'[could not save a copy: {e}]', file=sys.stderr)
