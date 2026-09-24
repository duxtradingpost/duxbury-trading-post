#!/usr/bin/env python3
"""Flag eBay listings sitting on the WRONG shipping policy for their price.

    python3 reports/ebay-shipping-check.py            # writes ebay-shipping-check.json
    python3 reports/ebay-shipping-check.py --print    # and prints it

Why this exists
---------------
Free shipping was removed store-wide on 2026-09-21, and the catalogue was split:

    Shipping (DTP)        $4.99 USPS Ground Advantage   - anything OVER $20
    Shipping (DTP)- ESE   $1.36 eBay Standard Envelope  - anything UNDER $20

**But a NEW eBay listing always defaults to `Shipping (DTP)`.** So every batch
listed re-creates the gap: on the same day the split was fixed, 125 cheap cards
had already drifted back onto $4.99. On a $1.99 card that is $6.98 to the buyer
against $3.35 - it does not sell.

The two errors are NOT equally bad, and this reports them separately:

  * CHEAP ON GROUND ADVANTAGE - costly, not dangerous. The card just sits.
  * DEAR ON ESE - the one that matters. eBay Standard Envelope has a hard $20
    declared-value cap with no insurance, so an expensive card shipped that way
    is outside eBay's terms and a loss is unrecoverable. Should always be zero.

*** THE BROWSE API LAGS AFTER A BULK EDIT. *** On 2026-09-22 a sweep moved ~124
listings to ESE; the policy page and the live item pages both showed $1.36
immediately, and this check still reported 120 of them on $4.99. It was reading
cached data and it was WRONG. So: a drop in the count confirms the edit worked,
but a count that has NOT dropped right after an edit proves nothing. Re-run a few
hours later, or settle it on the listing page - ebay.com/itm/<id> is the truth.

Uses Browse item_summary/search, which returns 200 listings per call - about
3 calls for the whole store. The per-item endpoint would be ~570 calls and burn
the daily Browse cap; see memory dtp-ebay-browse-quota, where a 30-minute job
did exactly that and then reported the 429s as a clean audit.
"""
import base64, json, os, sys, urllib.error, urllib.parse, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
APPID = os.path.expanduser('~/.dtp-ebay-appid')
CERT = os.path.expanduser('~/.dtp-ebay-cert')
OUT = os.path.join(HERE, 'ebay-shipping-check.json')

SELLER = 'duxburytradingpost'
ESE_CAP = 20.00          # eBay Standard Envelope declared-value ceiling
ESE_COST = 1.36
GA_COST = 4.99


def token():
    if not (os.path.exists(APPID) and os.path.exists(CERT)):
        sys.exit('missing ~/.dtp-ebay-appid or ~/.dtp-ebay-cert')
    basic = base64.b64encode(
        f'{open(APPID).read().strip()}:{open(CERT).read().strip()}'.encode()).decode()
    body = urllib.parse.urlencode({'grant_type': 'client_credentials',
                                   'scope': 'https://api.ebay.com/oauth/api_scope'}).encode()
    req = urllib.request.Request('https://api.ebay.com/identity/v1/oauth2/token', data=body,
                                 headers={'Authorization': 'Basic ' + basic,
                                          'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)['access_token']


def get(url, tok):
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok,
                                               'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def ship_cost(it):
    """Lowest shipping cost on the listing, or None when eBay does not say.

    None is NOT free - a listing with no shippingOptions is unknown, and
    treating unknown as $0 would invent a free-shipping fault that is not there.
    """
    opts = it.get('shippingOptions') or []
    costs = []
    for o in opts:
        c = (o.get('shippingCost') or {}).get('value')
        if c is not None:
            try: costs.append(float(c))
            except (TypeError, ValueError): pass
    return min(costs) if costs else None


def main():
    tok = token()
    items, offset, errors = [], 0, 0
    while offset < 10000:
        url = ('https://api.ebay.com/buy/browse/v1/item_summary/search'
               f'?limit=200&offset={offset}'
               f'&filter={urllib.parse.quote(f"sellers:{{{SELLER}}}")}'
               '&q=card')
        try:
            d = get(url, tok)
        except urllib.error.HTTPError as e:
            errors += 1
            print(f'ebay-shipping-check: HTTP {e.code} at offset {offset}', file=sys.stderr)
            break
        batch = d.get('itemSummaries') or []
        items += batch
        total = int(d.get('total') or 0)
        offset += 200
        if not batch or offset >= total:
            break

    if not items:
        print('ebay-shipping-check: no listings returned — NOT a clean check, '
              f'{os.path.basename(OUT)} left unchanged', file=sys.stderr)
        return 1

    cheap_on_ga, dear_on_ese, unknown = [], [], []
    for it in items:
        try:
            price = float((it.get('price') or {}).get('value'))
        except (TypeError, ValueError):
            continue
        sc = ship_cost(it)
        row = {'title': (it.get('title') or '')[:70], 'price': price,
               'ship': sc, 'itemId': it.get('itemId', '')}
        if sc is None:
            unknown.append(row)
        elif price > ESE_CAP and sc < 2.00:
            dear_on_ese.append(row)          # the dangerous one
        elif price <= ESE_CAP and sc > 2.00:
            cheap_on_ga.append(row)          # the costly one

    dear_on_ese.sort(key=lambda r: -r['price'])
    cheap_on_ga.sort(key=lambda r: r['price'])
    out = {'ran': str(date.today()), 'checked': len(items), 'errors': errors,
           'dear_on_ese': dear_on_ese, 'cheap_on_ga': cheap_on_ga,
           'unknown_shipping': unknown}
    json.dump(out, open(OUT, 'w'), indent=1)

    print(f'{len(items)} listings checked')
    print(f'  OVER ${ESE_CAP:.0f} on ESE (DANGEROUS, over cap): {len(dear_on_ese)}')
    print(f'  under ${ESE_CAP:.0f} on $4.99 GA (costly):        {len(cheap_on_ga)}')
    print(f'  shipping not reported:                     {len(unknown)}')
    if '--print' in sys.argv:
        for r in dear_on_ese[:10]:
            print(f'   !! ${r["price"]:>8.2f} ship ${r["ship"]:.2f}  {r["title"][:56]}')
        for r in cheap_on_ga[:10]:
            print(f'    . ${r["price"]:>8.2f} ship ${r["ship"]:.2f}  {r["title"][:56]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
