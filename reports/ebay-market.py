#!/usr/bin/env python3
"""Where each listing sits against the other people selling the same card, today.

    python3 reports/ebay-market.py [--print]

Sold prices need Terapeak or Marketplace Insights and cannot run headless. ACTIVE
competitor prices can: the Browse API answers "what is everyone else asking for
this card right now" on client credentials, no browser, no human. So this fills
the automatable half of the gap and runs in the 07:00 job.

What it is NOT: a comp. An asking price is what someone hopes to get, and the
Golden's actives ran $615-700 against verified SOLD comps of $525-629. Treat this
as position against competitors, not as value — the yardstick is still
comp-verified.json.

Flags two things worth acting on:
  highest on the board   nobody is asking more; you are the last card to sell
  undercut               several competitors materially below you
"""
import base64, importlib.util, json, os, re, statistics, sys
from datetime import date
import urllib.error, urllib.parse, urllib.request

HERE  = os.path.dirname(os.path.abspath(__file__))
OUT   = os.path.join(HERE, 'ebay-market.json')
APPID = os.path.expanduser('~/.dtp-ebay-appid')
CERT  = os.path.expanduser('~/.dtp-ebay-cert')
UNDERCUT = 0.85      # competitors this far below you are undercutting, not noise
MIN_RIVALS = 3       # fewer than this is not a market


def token():
    basic = base64.b64encode(
        f'{open(APPID).read().strip()}:{open(CERT).read().strip()}'.encode()).decode()
    body = urllib.parse.urlencode({'grant_type': 'client_credentials',
                                   'scope': 'https://api.ebay.com/oauth/api_scope'}).encode()
    req = urllib.request.Request('https://api.ebay.com/identity/v1/oauth2/token', data=body,
                                 headers={'Authorization': 'Basic ' + basic,
                                          'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)['access_token']


def _comp_tools():
    """Reuse the matching rules from comp-tools.py rather than write them twice.

    Without them this check is worthless: a bare keyword search returned the
    Golden "against" listings from $20 to $30,000 and put McMillan's median at $2,
    because it swept in base cards and unrelated lots. Every one of those rules —
    print run both ways, grade, year, card number, rare words — exists because it
    caught a real false match."""
    spec = importlib.util.spec_from_file_location('ct', os.path.join(HERE, 'comp-tools.py'))
    m = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ['comp-tools']
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    finally:
        sys.argv = argv
    return m


CT = _comp_tools()


def query_for(title):
    """Distinguishing tokens only. Whole titles match nothing; two words match
    everything. Same lesson as comp-tools.py."""
    t = re.sub(r'[^A-Za-z0-9/#\- ]', ' ', title)
    drop = {'the', 'and', 'rc', 'card', 'trading', 'sports'}
    words = [w for w in t.split() if len(w) > 2 and w.lower() not in drop]
    return ' '.join(words[:9])


def rivals(tok, title, mine_id):
    q = urllib.parse.urlencode({'q': query_for(title), 'limit': 50,
                                'filter': 'buyingOptions:{FIXED_PRICE}'})
    req = urllib.request.Request(
        f'https://api.ebay.com/buy/browse/v1/item_summary/search?{q}',
        headers={'Authorization': 'Bearer ' + tok, 'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    card = CT.card_facts(title)
    out, rejected = [], 0
    for it in d.get('itemSummaries', []):
        if mine_id and mine_id in (it.get('itemId') or ''):
            continue                      # never count our own listing as a rival
        ok, _ = CT.matches(card, it.get('title') or '')
        if not ok:
            rejected += 1
            continue
        try:
            out.append(float(it['price']['value']))
        except Exception:
            pass
    return out, rejected


def already_ran_today():
    """Has today's competitor sweep already run?

    Same quota story as ebay-audit.py: one search per listing x 48 briefing ticks
    a day exhausts the 5,000-call Browse allowance, after which every call 429s
    and this script reports "0 listings flagged" — indistinguishable from a real
    sweep that found nothing. Competitor pricing does not move fast enough to
    justify 48 passes; once a day is plenty."""
    try:
        return json.load(open(OUT)).get('ran') == str(date.today())
    except Exception:
        return False


def main():
    if '--once-daily' in sys.argv and already_ran_today():
        return 0
    tok = token()
    try:
        ids = json.load(open(os.path.join(HERE, 'ebay-itemids.json')))
    except Exception:
        sys.exit('no ebay-itemids.json')
    import csv, glob
    exp = max(glob.glob(os.path.join(HERE, 'products_export*.csv')), key=os.path.getmtime)
    info = {r['Variant SKU']: (r['Title'], float(r['Variant Price'] or 0))
            for r in csv.DictReader(open(exp))
            if r.get('Variant SKU') and r.get('Status') == 'active'}

    rows, errors, looked = [], 0, 0
    for sku, iid in ids.items():
        if sku not in info:
            continue
        title, mine = info[sku]
        if mine <= 0:
            continue
        looked += 1
        try:
            prices, rejected = rivals(tok, title, iid)
        except urllib.error.HTTPError:
            errors += 1
            continue
        if len(prices) < MIN_RIVALS:
            continue
        prices.sort()
        med = statistics.median(prices)
        cheaper = [p for p in prices if p < mine * UNDERCUT]
        flag = None
        if mine > max(prices):
            flag = 'highest on the board'
        elif len(cheaper) >= 3:
            flag = f'{len(cheaper)} listed below'
        if flag:
            rows.append({'sku': sku, 'title': title[:60], 'mine': mine,
                         'rivals': len(prices), 'rejected': rejected,
                         'lo': round(min(prices), 2),
                         'median': round(med, 2), 'hi': round(max(prices), 2),
                         'flag': flag})
    rows.sort(key=lambda r: -r['mine'])
    # An all-errors sweep is not "nothing flagged" — keep the last real result.
    if looked and errors == looked:
        print(f'ebay-market: ALL {errors} searches failed (rate limit or token) — '
              f'{os.path.basename(OUT)} left unchanged, NOT a clean sweep', file=sys.stderr)
        return 1
    json.dump({'checked': len(ids), 'errors': errors, 'flagged': rows,
               'ran': str(date.today())}, open(OUT, 'w'), indent=1)
    warn = f', {errors} FAILED to load' if errors else ''
    print(f'{len(rows)} listings flagged against live competitors{warn} -> {os.path.basename(OUT)}')
    if '--print' in sys.argv:
        for r in rows[:15]:
            print(f"  ${r['mine']:>8.2f}  vs ${r['lo']:.0f}-{r['hi']:.0f} "
                  f"(med ${r['median']:.0f}, n={r['rivals']})  {r['flag']:<22} {r['title'][:34]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
