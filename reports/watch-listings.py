#!/usr/bin/env python3
"""Watch eBay for specific cards and email when one comes up worth a look.

    python3 reports/watch-listings.py            # check, email anything new
    python3 reports/watch-listings.py --dry-run  # check, print, send nothing

Each entry in reports/watchlist.json names a card and what counts as worth a
look: any AUCTION (auctions are where these actually sell below the asks), or a
fixed price at or under `max_price`. Every listing is reported once; a listing
seen before is reported again only if its price drops to a new low under the
threshold. State lives in reports/watch-state.json.

Started 2026-09-22 for the 2026 Bowman Crystallized Roman Anthony Gold /50:
raw copies sold $810-910 at auction, while every Buy It Now sat at $1,500-5,000
and the seller of the #19/50 auto-declined $700, $800 and $950.

Title filters are all-must-match regexes plus excludes, because an eBay search
mixes in Leaf "Gold Crystal" autos and other parallels (see check-deal.py for
why eyeballing a search fools you).

Quota: one Browse search per entry per run. Run every 2 hours that is ~12 calls
a day per card against a 5,000/day cap (memory: dtp-ebay-browse-quota).
"""
import base64, json, os, re, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
WATCH = os.path.join(HERE, 'watchlist.json')
STATE = os.path.join(HERE, 'watch-state.json')
DRY = '--dry-run' in sys.argv


def token():
    appid = open(os.path.expanduser('~/.dtp-ebay-appid')).read().strip()
    cert = open(os.path.expanduser('~/.dtp-ebay-cert')).read().strip()
    req = urllib.request.Request(
        'https://api.ebay.com/identity/v1/oauth2/token',
        urllib.parse.urlencode({'grant_type': 'client_credentials',
                                'scope': 'https://api.ebay.com/oauth/api_scope'}).encode(),
        {'Authorization': 'Basic ' + base64.b64encode(f'{appid}:{cert}'.encode()).decode(),
         'Content-Type': 'application/x-www-form-urlencoded'})
    return json.load(urllib.request.urlopen(req, timeout=30))['access_token']


def search(tok, q):
    url = 'https://api.ebay.com/buy/browse/v1/item_summary/search?' + urllib.parse.urlencode(
        {'q': q, 'limit': 200})
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok,
                                               'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'})
    return json.load(urllib.request.urlopen(req, timeout=30)).get('itemSummaries', [])


def price_of(it):
    # An auction's `price` is empty until bid on; currentBidPrice is what it stands at.
    p = it.get('currentBidPrice') or it.get('price') or {}
    return float(p.get('value', 0) or 0)


def send(subject, text):
    key = open(os.path.expanduser('~/.dtp-briefing-key')).read().strip()
    html = '<pre style="font:14px/1.5 -apple-system,Helvetica,Arial,sans-serif;white-space:pre-wrap">' + \
        text.replace('&', '&amp;').replace('<', '&lt;') + '</pre>'
    req = urllib.request.Request(
        'https://duxburytradingpost.com/api/briefing',
        data=json.dumps({'subject': subject, 'text': text, 'html': html}).encode(),
        headers={'Content-Type': 'application/json; charset=utf-8', 'X-DTP-Key': key,
                 # Cloudflare rejects urllib's default agent before the Worker sees it.
                 'User-Agent': 'DuxburyTradingPost-Watch/1.0 (+https://duxburytradingpost.com)'})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f'[emailed: HTTP {r.status}]')


def main():
    watch = json.load(open(WATCH))
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    tok = token()
    for w in watch:
        seen = state.setdefault(w['name'], {})
        must = [re.compile(p, re.I) for p in w.get('must', [])]
        excl = [re.compile(p, re.I) for p in w.get('exclude', [])]
        hits = []
        try:
            items = search(tok, w['query'])
        except urllib.error.HTTPError as e:
            # Never let an API failure read as "nothing listed" (dtp-ebay-browse-quota).
            print(f'!! {w["name"]}: eBay search failed HTTP {e.code} - NOT a clean check', file=sys.stderr)
            continue
        for it in items:
            title = it.get('title', '')
            if not all(m.search(title) for m in must) or any(x.search(title) for x in excl):
                continue
            opts = it.get('buyingOptions', [])
            px = price_of(it)
            auction = 'AUCTION' in opts
            if not auction and px > w['max_price']:
                continue
            iid = it['itemId']
            prev = seen.get(iid)
            if prev is not None and px >= prev:
                continue            # already reported at this price or lower
            seen[iid] = px
            kind = 'AUCTION' if auction else 'Buy It Now' + (' / Best Offer' if 'BEST_OFFER' in opts else '')
            ends = it.get('itemEndDate', '')[:16].replace('T', ' ')
            hits.append(f'${px:,.2f}  {kind}' + (f'  (ends {ends} UTC)' if auction and ends else '') +
                        f'\n{title}\n{it.get("itemWebUrl", "").split("?")[0]}\n')
        print(f'{w["name"]}: {len(items)} results, {len(hits)} new')
        if hits:
            body = (f'{w["name"]}\nAlert when: any auction, or Buy It Now at or under ${w["max_price"]:,.0f}.\n'
                    f'{w.get("note", "")}\n\n' + '\n'.join(hits))
            subject = f'Card watch: {w["name"]} ({len(hits)} new)'
            if DRY:
                print(body)
            else:
                send(subject, body)
    if not DRY:
        json.dump(state, open(STATE, 'w'), indent=1)
    print('checked', datetime.now().strftime('%Y-%m-%d %H:%M'))


if __name__ == '__main__':
    main()
