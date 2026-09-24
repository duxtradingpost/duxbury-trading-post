#!/usr/bin/env python3
"""Find cards whose website (Shopify) price no longer matches the live eBay price.

    python3 reports/price-drift.py               # check, write price-drift.json
    python3 reports/price-drift.py --print       # and show it
    python3 reports/price-drift.py --once-daily  # skip if already run today (07:00 job)

eBay is the source of truth for price (memory: dtp-ebay-shopify-sync) and the
InfoShore app is meant to copy every eBay price to Shopify. On 2026-09-22 a full
comparison found 51 cards out of step - 47 dearer on the website than on eBay,
most still at their 8 Sept price, with Price Sync switched ON in the app. So the
sync misses some kinds of eBay price edit, and nothing noticed for two weeks.
This check is how it gets noticed. It only REPORTS; it never writes a price.

Matching is by normalised title, because the synced products carry no eBay item
id. Skipped: Personal / $9,999 placeholders, sold-out products, and titles with
several eBay copies at different prices (no way to tell which copy is which).

Quota: ~7 Browse calls a run (bulk seller search, 200 a page), far under the
5,000/day cap that the per-item scripts used to exhaust (dtp-ebay-browse-quota).
A failed run prints loudly and leaves yesterday's result on disk - it never
writes an empty list that would read as "all prices match".
"""
import base64, collections, json, os, re, sys, urllib.parse, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'price-drift.json')
SELLER = 'duxburytradingpost'
# Sports singles, sealed, graded, and the card-game categories the store lists in.
CATEGORIES = ['261328', '183454', '183050', '261329', '261330']
SHOP_URL = 'https://hmbhxb-y0.myshopify.com/admin/api/2026-07/graphql.json'


def ebay_token():
    appid = open(os.path.expanduser('~/.dtp-ebay-appid')).read().strip()
    cert = open(os.path.expanduser('~/.dtp-ebay-cert')).read().strip()
    req = urllib.request.Request(
        'https://api.ebay.com/identity/v1/oauth2/token',
        urllib.parse.urlencode({'grant_type': 'client_credentials',
                                'scope': 'https://api.ebay.com/oauth/api_scope'}).encode(),
        {'Authorization': 'Basic ' + base64.b64encode(f'{appid}:{cert}'.encode()).decode(),
         'Content-Type': 'application/x-www-form-urlencoded'})
    return json.load(urllib.request.urlopen(req, timeout=30))['access_token']


def ebay_listings():
    tok = ebay_token()
    items = {}
    for cat in CATEGORIES:
        off = 0
        while True:
            url = 'https://api.ebay.com/buy/browse/v1/item_summary/search?' + urllib.parse.urlencode(
                {'category_ids': cat, 'filter': f'sellers:{{{SELLER}}}', 'limit': 200, 'offset': off})
            d = json.load(urllib.request.urlopen(urllib.request.Request(
                url, headers={'Authorization': 'Bearer ' + tok, 'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'}),
                timeout=30))
            for it in d.get('itemSummaries', []):
                # Auctions report the current bid as `price` - not a list price.
                if 'FIXED_PRICE' in it.get('buyingOptions', []):
                    items[it['itemId']] = (it['title'], float(it['price']['value']))
            off += 200
            if off >= d.get('total', 0):
                break
    return items


def shopify_active():
    token = open(os.path.expanduser('~/.dtp-shopify-token')).read().strip()
    q = ('query($a:String){products(first:250,after:$a,query:"status:active"){'
         'pageInfo{hasNextPage endCursor} nodes{title tags '
         'variants(first:1){nodes{price inventoryQuantity}}}}}')
    out, after = [], None
    while True:   # paginated: a bare first:250 is a truncation (dtp-shopify-tag-conventions)
        req = urllib.request.Request(SHOP_URL, json.dumps({'query': q, 'variables': {'a': after}}).encode(),
                                     {'Content-Type': 'application/json', 'X-Shopify-Access-Token': token})
        d = json.load(urllib.request.urlopen(req, timeout=60))
        if 'errors' in d:
            raise RuntimeError(json.dumps(d['errors'])[:300])
        c = d['data']['products']
        out += c['nodes']
        if not c['pageInfo']['hasNextPage']:
            return out
        after = c['pageInfo']['endCursor']


norm = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())


def main():
    if '--once-daily' in sys.argv and os.path.exists(OUT):
        try:
            if json.load(open(OUT)).get('ran') == str(date.today()):
                print('price-drift: already ran today')
                return
        except Exception:
            pass
    try:
        ebay = ebay_listings()
        shop = shopify_active()
    except Exception as e:
        print(f'!! price-drift FAILED ({e}) - previous result left in place, NOT a clean check',
              file=sys.stderr)
        sys.exit(1)
    if not ebay:
        print('!! price-drift: eBay returned no listings - NOT a clean check', file=sys.stderr)
        sys.exit(1)

    by_title = collections.defaultdict(set)
    for title, px in ebay.values():
        by_title[norm(title)].add(px)
    drift, checked = [], 0
    for p in shop:
        v = p['variants']['nodes'][0]
        site = float(v['price'])
        if 'Personal' in p['tags'] or site >= 9999 or (v['inventoryQuantity'] or 0) <= 0:
            continue
        prices = by_title.get(norm(p['title']))
        if not prices or len(prices) != 1:
            continue
        checked += 1
        ebay_px = next(iter(prices))
        if abs(ebay_px - site) >= 0.01:
            drift.append({'title': p['title'], 'ebay': ebay_px, 'site': site})
    drift.sort(key=lambda r: -abs(r['site'] - r['ebay']))
    json.dump({'ran': str(date.today()), 'ebay_listings': len(ebay), 'checked': checked,
               'drift': drift}, open(OUT, 'w'), indent=1)
    print(f'price-drift: {len(drift)} of {checked} matched cards differ from eBay')
    if '--print' in sys.argv:
        for r in drift:
            print(f"  eBay ${r['ebay']:>8.2f}  site ${r['site']:>8.2f}  {r['title'][:70]}")


if __name__ == '__main__':
    main()
