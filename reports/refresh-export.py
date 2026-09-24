#!/usr/bin/env python3
"""Pull a fresh product export straight from Shopify.

    python3 reports/refresh-export.py

Everything downstream — the daily briefing, the market audit, the Wednesday
Instagram job — reads the newest products_export*.csv it can find. Until this
existed, that file was a snapshot made by hand, so newly listed cards were
invisible to all three and the drift only ever grew. This closes that.

Needs a Shopify Admin API token in ~/.dtp-shopify-token (outside the repo — a
secret in a tracked file is a secret you have published). Create one in Shopify:
Settings -> Apps and sales channels -> Develop apps -> Create an app -> Configure
Admin API scopes -> read_products and read_inventory -> Install -> reveal the
Admin API access token. It starts "shpat_".

read_inventory is not optional: cost per item lives on inventoryItem.unitCost and
without it nothing downstream can compute a break-even.
"""
import csv, json, os, sys, urllib.error, urllib.request
from datetime import date

HERE  = os.path.dirname(os.path.abspath(__file__))
# The canonical myshopify domain, which is what the Admin API and OAuth both
# key on. duxburytradingpost.myshopify.com serves the storefront but is not the
# shop identity — the OAuth callback returns hmbhxb-y0.
SHOP  = 'hmbhxb-y0.myshopify.com'
API   = '2026-07'
TOKEN = os.path.expanduser('~/.dtp-shopify-token')

# Only the columns anything downstream actually reads. daily-briefing.py takes
# Handle, Title, Status, Cost per item, Variant Price, Variant Barcode;
# ig-wednesday.py adds Variant SKU. Image Src is kept for reference even though
# images are now resolved live (export handles go stale when a card is renamed).
COLS = ['Handle', 'Title', 'Status', 'Tags', 'Variant SKU', 'Variant Price',
        'Cost per item', 'Variant Barcode', 'Variant Inventory Qty', 'Image Src']

QUERY = """
query($after: String) {
  products(first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      handle title status tags
      featuredImage { url }
      variants(first: 1) {
        nodes {
          sku price barcode inventoryQuantity
          inventoryItem { unitCost { amount } }
        }
      }
    }
  }
}
"""


def token():
    if not os.path.exists(TOKEN):
        print(f'no {TOKEN} — see the docstring for how to create one', file=sys.stderr)
        sys.exit(2)
    t = open(TOKEN).read().strip()
    if not t:
        print(f'{TOKEN} is empty', file=sys.stderr)
        sys.exit(2)
    return t


def fetch(tok):
    out, after = [], None
    while True:
        body = json.dumps({'query': QUERY, 'variables': {'after': after}}).encode()
        req = urllib.request.Request(
            f'https://{SHOP}/admin/api/{API}/graphql.json', data=body,
            headers={'Content-Type': 'application/json', 'X-Shopify-Access-Token': tok})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            print(f'Shopify returned HTTP {e.code}: {e.read().decode()[:200]}', file=sys.stderr)
            sys.exit(1)
        if d.get('errors'):
            print(f'GraphQL errors: {json.dumps(d["errors"])[:300]}', file=sys.stderr)
            sys.exit(1)
        p = d['data']['products']
        out.extend(p['nodes'])
        if not p['pageInfo']['hasNextPage']:
            return out
        after = p['pageInfo']['endCursor']


def row(n):
    v = (n.get('variants') or {}).get('nodes') or [{}]
    v = v[0]
    cost = ((v.get('inventoryItem') or {}).get('unitCost') or {}).get('amount')
    return {
        'Handle': n.get('handle') or '',
        'Title': n.get('title') or '',
        'Status': (n.get('status') or '').lower(),
        'Tags': ', '.join(n.get('tags') or []),
        'Variant SKU': v.get('sku') or '',
        'Variant Price': v.get('price') or '',
        'Cost per item': cost or '',
        'Variant Barcode': v.get('barcode') or '',
        'Variant Inventory Qty': v.get('inventoryQuantity') if v.get('inventoryQuantity') is not None else '',
        'Image Src': ((n.get('featuredImage') or {}).get('url') or ''),
    }


def main():
    nodes = fetch(token())
    rows = [row(n) for n in nodes]
    dest = os.path.join(HERE, f'products_export_{date.today().isoformat()}.csv')
    with open(dest, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)

    active = sum(1 for r in rows if r['Status'] == 'active')
    nocost = sum(1 for r in rows if r['Status'] == 'active' and not r['Cost per item'])
    print(f'{len(rows)} products ({active} active) -> {os.path.basename(dest)}')
    if nocost:
        print(f'{nocost} active products have no cost — they cannot be priced downstream')

    # Keep the two most recent exports. Older ones are only ever noise, and
    # newest_export() picks by mtime so a stale straggler is harmless but
    # confusing when someone reads the directory.
    keep = sorted((f for f in os.listdir(HERE) if f.startswith('products_export')),
                  key=lambda f: os.path.getmtime(os.path.join(HERE, f)), reverse=True)[:2]
    for f in os.listdir(HERE):
        if f.startswith('products_export') and f not in keep:
            os.remove(os.path.join(HERE, f))
    return 0


if __name__ == '__main__':
    sys.exit(main())
