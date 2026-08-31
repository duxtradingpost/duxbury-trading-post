#!/usr/bin/env python3
"""Check a fresh Shopify export against the comp work.

    python3 reports/comp-reconcile.py                  # newest products_export*.csv
    python3 reports/comp-reconcile.py path/to/file.csv

Reads reports/comp-data.json — the 167 cards comped by hand on 27 August 2026 —
and reports where the live prices now sit against those comps. That file carries
costs and so is gitignored along with the rest of reports/*.json; it lives only
on this machine.

Two things this deliberately does NOT do. It does not treat the comped market as
gospel: 137 of those cards are raw and their ranges were read off eBay search
results that mix graded sales in, so every range skews high. And it does not
suggest raising anything, for the same reason. Use eBay's own Price Guide, which
splits Ungraded from PSA 9 and PSA 10, for anything you intend to raise.
"""
import csv, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH = [HERE, os.path.expanduser('~/Desktop'), os.path.expanduser('~/Downloads')]

FEE, PER_LOW, PER_HIGH, ESE, GA = 0.1325, 0.30, 0.40, 0.78, 6.07
ESE_CAP = 20 - ESE          # 19.22 — item + postage must clear $20
DEAD_TOP = 26.00            # above this, losing the envelope stops mattering

GRADE_WORDS = ('graded', 'psa', 'bgs', 'sgc', 'cgc')
SEALED_TAGS = {'sealed', 'box', 'boxes', 'hobby box', 'blaster',
               'mega box', 'pack', 'packs', 'case', 'wax'}


def newest_export():
    files = []
    for d in SEARCH:
        try:
            files += glob.glob(os.path.join(d, 'products_export*.csv'))
        except OSError:
            continue
    return max(files, key=os.path.getmtime) if files else None


def net(p, graded):
    ship = GA if graded else (ESE if p <= ESE_CAP else GA)
    return p * (1 - FEE) - (PER_LOW if p <= 10 else PER_HIGH) - ship


def is_graded(row):
    tags = [t.strip().lower() for t in (row.get('Tags') or '').split(',')]
    return any(t in GRADE_WORDS for t in tags) or \
        bool(re.search(r'\b(psa|bgs|sgc|cgc)\b', row['Title'], re.I))


def is_sealed(row):
    return any(t.strip().lower() in SEALED_TAGS
               for t in (row.get('Tags') or '').split(','))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else newest_export()
    if not path:
        sys.exit('No products_export*.csv found in reports/, Desktop or Downloads.')
    print(f'export : {path}')
    print(f'        {os.path.getmtime(path):.0f} -> ' +
          __import__('datetime').datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M'))

    rows = [r for r in csv.DictReader(open(path)) if r['Title'].strip()]
    active = [r for r in rows if r['Status'] == 'active']
    live = {r['Title']: r for r in active}
    comps = json.load(open(os.path.join(HERE, 'comp-data.json')))
    print(f'active : {len(active)} listings, ${sum(float(r["Variant Price"] or 0) for r in active):,.2f} listed\n')

    # ---- 1. the dead zone -------------------------------------------------
    # An envelope-eligible card priced between $19.22 and ~$26 pays Ground
    # Advantage instead, so it nets less than the same card priced lower.
    dead = [r for r in active
            if ESE_CAP < float(r['Variant Price'] or 0) <= DEAD_TOP and not is_graded(r)]
    print(f'--- 1. envelope dead zone: {len(dead)} raw cards priced ${ESE_CAP:.2f}-${DEAD_TOP:.0f} ---')
    if dead:
        give = sum(net(ESE_CAP, False) - net(float(r['Variant Price']), False) for r in dead)
        print(f'    dropping them to ${ESE_CAP:.2f} is worth ${give:,.2f} in total')
        for r in sorted(dead, key=lambda r: -float(r['Variant Price']))[:12]:
            p = float(r['Variant Price'])
            print(f'      ${p:>6.2f}  (+${net(ESE_CAP, False) - net(p, False):.2f})  {r["Title"][:58]}')
    else:
        print('    clear')
    print()

    # ---- 2. movement against the comps -----------------------------------
    above, inrange, below, gone = [], [], [], []
    for c in comps:
        r = live.get(c['title'])
        if r is None:
            gone.append(c)
            continue
        p = float(r['Variant Price'] or 0)
        if not c['n']:
            continue
        if p > c['hi'] * 1.05:
            above.append((c, p))
        elif p < c['lo'] * 0.9:
            below.append((c, p))
        else:
            inrange.append((c, p))
    print(f'--- 2. against the comped ranges ---')
    print(f'    in range        {len(inrange)}')
    print(f'    still above     {len(above)}')
    print(f'    now below       {len(below)}   <- ranges skew high, so check before raising')
    print(f'    no longer listed {len(gone)}   <- sold, archived or renamed')
    if gone:
        for c in gone[:8]:
            print(f'      was ${c["listed"]:>7.2f}  {c["name"][:56]}')
    print()
    if above:
        print('    worst still-above, by dollars over the top of range:')
        for c, p in sorted(above, key=lambda t: -(t[1] - t[0]['hi']))[:10]:
            print(f'      ${p:>7.2f} vs ${c["lo"]:.0f}-{c["hi"]:.0f}   {c["name"][:50]}')
        print()

    # ---- 3. the specific open items --------------------------------------
    print('--- 3. open items from the comp run ---')
    watch = [
        ('BCP-22', 'Roman Anthony Orange Shimmer', 'raw; priced off PSA 10 comps by mistake'),
        ('Premier Neon Green', 'Brock Bowers Neon Green Shock', 'ungraded Price Guide says $7.00'),
        ('Purple Ice', 'Tyler Warren Purple Ice', 'ungraded Price Guide says $13.25'),
        ('Downtown', 'Matthew Golden Downtown!', 'title still says The Rookies?'),
    ]
    for needle, label, why in watch:
        hit = [r for r in active if needle.lower() in r['Title'].lower()]
        for r in hit:
            flag = ' <-- TITLE NOT FIXED' if needle == 'Downtown' and 'Rookies' in r['Title'] else ''
            print(f'    ${float(r["Variant Price"]):>7.2f}  {label:<32} {why}{flag}')
    print()

    # ---- 4. sealed ---------------------------------------------------------
    sealed = [r for r in active if is_sealed(r)]
    print(f'--- 4. sealed product: {len(sealed)} tagged ---')
    if sealed:
        for r in sealed:
            print(f'    ${float(r["Variant Price"]):>7.2f}  {r["Title"][:60]}')
        print('    the Sealed chip is live on the inventory page')
    else:
        print('    none tagged yet, so the Sealed chip stays hidden')


if __name__ == '__main__':
    main()
