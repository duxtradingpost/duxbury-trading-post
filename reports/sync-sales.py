#!/usr/bin/env python3
"""Append Shopify orders to the Sales sheet in purchase-log.xlsx.

    python3 reports/sync-sales.py [--dry-run]

The Sales sheet was maintained by hand and, on 8 September, was missing roughly
70% of the revenue that had actually come through — which made the whole business
look like it had stalled when its best week ever was in progress. Anything
maintained by hand drifts; this stops it.

Idempotent: every appended row records "Shopify order #NNNN." in the notes, and
orders already named there are skipped. Safe to run repeatedly.

Fees are ESTIMATED from the DTP model, not read from the marketplace — eBay's
actual fee never reaches Shopify, and the imported orders carry no shipping. That
matches how the existing rows were built. Estimated fees are fine for margin
direction and wrong for tax filing; the bank is the authority for the latter.
"""
import json, os, re, shutil, sys, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
LOG  = os.path.join(HERE, '..', 'whatnot', 'purchase-log.xlsx')
SHOP = 'hmbhxb-y0.myshopify.com'
TOKEN = os.path.expanduser('~/.dtp-shopify-token')

FEE_EBAY, ESE, GA = 0.1325, 0.78, 6.07
FEE_WEB, WEB_FIXED = 0.029, 0.30          # Shopify Payments online rate
EBAY_TAG = 'ebay importer'

QUERY = """
query($after:String){
  orders(first:50, after:$after, sortKey:CREATED_AT, query:"status:any"){
    pageInfo{hasNextPage endCursor}
    nodes{
      name createdAt tags
      lineItems(first:20){nodes{
        title quantity
        originalUnitPriceSet{shopMoney{amount}}
        variant{sku inventoryItem{unitCost{amount}}}
      }}
    }
  }
}"""


def fetch():
    tok = open(TOKEN).read().strip()
    out, after = [], None
    while True:
        req = urllib.request.Request(
            f'https://{SHOP}/admin/api/2026-07/graphql.json',
            data=json.dumps({'query': QUERY, 'variables': {'after': after}}).encode(),
            headers={'Content-Type': 'application/json', 'X-Shopify-Access-Token': tok})
        d = json.load(urllib.request.urlopen(req, timeout=45))
        if d.get('errors'):
            sys.exit(f'GraphQL: {str(d["errors"])[:300]}')
        p = d['data']['orders']
        out.extend(p['nodes'])
        if not p['pageInfo']['hasNextPage']:
            return out
        after = p['pageInfo']['endCursor']


def fees(channel, price):
    """What the sale cost to make, per the DTP model."""
    if channel == 'eBay':
        ship = ESE if price <= 19.22 else GA
        per = 0.30 if price <= 10 else 0.40
        return round(price * FEE_EBAY + per + ship, 2)
    ship = ESE if price <= 19.22 else GA
    return round(price * FEE_WEB + WEB_FIXED + ship, 2)


def main():
    dry = '--dry-run' in sys.argv
    import openpyxl
    wb = openpyxl.load_workbook(LOG)
    ws = wb['Sales']

    seen = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        note = str(row[8] or '')
        for m in re.findall(r'#(\d{3,})', note):
            seen.add('#' + m)

    new = []
    for o in fetch():
        if o['name'] in seen:
            continue
        channel = 'eBay' if any(EBAY_TAG in t.lower() for t in (o.get('tags') or [])) else 'Website'
        for li in o['lineItems']['nodes']:
            qty = li.get('quantity') or 1
            price = float(li['originalUnitPriceSet']['shopMoney']['amount']) * qty
            v = li.get('variant') or {}
            uc = ((v.get('inventoryItem') or {}).get('unitCost') or {}).get('amount')
            cost = round(float(uc) * qty, 2) if uc else None
            new.append({'date': o['createdAt'][:10], 'card': li['title'],
                        'channel': channel, 'price': round(price, 2),
                        'fees': fees(channel, price), 'cost': cost,
                        'note': f"Shopify order {o['name']}."})

    new.sort(key=lambda r: r['date'])
    if not new:
        print('nothing new — Sales is already current')
        return 0

    gross = sum(r['price'] for r in new)
    nocost = sum(1 for r in new if r['cost'] is None)
    print(f'{len(new)} new sale line(s), ${gross:,.2f} gross')
    for r in new[:12]:
        print(f"  {r['date']}  {r['channel']:<8} ${r['price']:>8.2f}  {r['card'][:46]}")
    if len(new) > 12:
        print(f'  ...and {len(new) - 12} more')
    if nocost:
        print(f'{nocost} line(s) have no cost basis — profit will be blank for those')
    if dry:
        print('\n--dry-run: nothing written')
        return 0

    shutil.copy2(LOG, LOG.replace('.xlsx', f'.backup-sync-{date.today().isoformat()}.xlsx'))
    r = ws.max_row + 1
    for s in new:
        ws.cell(r, 1, s['date'])          # dates are stored as strings in this book
        ws.cell(r, 2, s['card'])
        ws.cell(r, 3, s['channel'])
        ws.cell(r, 4, s['price'])
        ws.cell(r, 5, s['fees'])
        ws.cell(r, 6, s['cost'] if s['cost'] is not None else None)
        ws.cell(r, 7, f'=IF(D{r}=0,0,D{r}-N(E{r})-N(F{r}))')
        ws.cell(r, 8, f'=IF(D{r}=0,"",G{r}/D{r})')
        ws.cell(r, 9, s['note'])
        r += 1
    wb.save(LOG)
    print(f'\nappended to {os.path.basename(LOG)} (backup alongside it)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
