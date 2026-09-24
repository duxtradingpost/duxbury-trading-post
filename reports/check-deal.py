#!/usr/bin/env python3
"""Is this deal alert real? Puts the SportsCardsPro guide price next to what the
card is actually being asked for on eBay right now.

    python3 reports/check-deal.py "2025 Topps Chrome Cooper Flagg #251 Blue Refractor /150"
    python3 reports/check-deal.py "<card>" --price 1035     # what they want for it
    python3 reports/check-deal.py "<card>" --all            # every SCP product matched

Why this exists
---------------
On 2026-09-10 a SportsCardsPro alert claimed a $989.28 saving on a Cooper Flagg
Blue Refractor /150 listed at $1,035, against a guide of $2,025 ungraded. Craig
thought the number looked wrong. A quick eyeball of eBay seemed to confirm it:
piles of "Blue" Flagg #251 cards at $599-900, far under the guide.

**That eyeball was wrong, and this tool exists because of it.** Those cheap cards
were **Blue X-Fractors** — a different, commoner parallel. Filtering to the
actual Blue Refractor /150 leaves nine listings asking $1,030, $1,300, $1,800,
$1,800, $2,200 and up. The guide sat at the MEDIAN ask, not above the market, and
the $1,035 listing was the cheapest of the nine.

So the lesson is not "the guide lies". It is that **eyeballing a search mixes
parallels together and will fool you in whichever direction you were leaning.**
Three filters below prevent it: player surname, card number, and an exact
parallel match in BOTH directions — "Blue RayWave Refractor" contains every word
of "Blue Refractor" and is a dearer card, so a one-directional test lets it in
and drags the median up by hundreds. That is the same asymmetry that once priced
a "Gold" parallel off a "Gold Interstellar" in scp-comps.

What this can and cannot settle
-------------------------------
**Asking prices are not sold prices.** They are an upper bound: a card can sell
for less than every ask, never for more than all of them. That asymmetry is
enough to falsify a guide price that sits above every ask, and enough to show
where a listing sits among its competition. It cannot prove a guide is right —
nine people asking $2,000 does not mean anyone pays it.

Still worth checking on any alert over a couple of hundred dollars, because the
guide is weakest exactly where the money is: a current release of a hot rookie,
where prices spike and fall faster than any guide updates. The minimum-saving
filters on the alerts screen the SIZE of a discount, never whether the baseline
deserves belief.
"""
import argparse, importlib.util, json, os, statistics, sys, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, path))
    m = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, [name]
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    finally:
        sys.argv = argv
    return m


SCP = _load('scp', 'scp-comps.py')
EB  = _load('eb', 'ebay-audit.py')

GRADES = [('Ungraded', 'loose-price'), ('Grade 8', 'condition-18-price'),
          ('Grade 9', 'graded-price'), ('Grade 9.5', 'condition-19-price'),
          ('PSA 10', 'manual-only-price'), ('BGS 10', 'bgs-10-price')]

# Finish words that distinguish one parallel from another. Shown so a mismatch
# between what you are buying and what the guide priced is visible at a glance.
FINISHES = ('x-fractor', 'xfractor', 'refractor', 'wave', 'raywave', 'prizm', 'holo',
            'shimmer', 'mojo', 'nebula', 'pandora', 'sparkle', 'disco', 'lazer',
            'laser', 'superfractor', 'atomic', 'speckle', 'cracked ice', 'moon')
COLOURS  = ('red', 'orange', 'yellow', 'green', 'blue', 'purple', 'pink', 'black',
            'white', 'gold', 'silver', 'bronze', 'aqua', 'teal', 'emerald',
            'sapphire', 'ruby', 'citrine', 'onyx')


def money(c):
    return None if c in (None, '', 0) else round(int(c) / 100.0, 2)


def scp_lookup(title, show_all=False):
    tok = SCP.token()
    long_q, short_q = SCP.query_for(title)
    prods = SCP.api_products(long_q, tok)
    if not prods and short_q != long_q:
        prods = SCP.api_products(short_q, tok) or []
    prods = prods or []
    hits = [p for p in prods if SCP.scp_matches(p, title)[0]]
    if show_all:
        return prods, hits
    return prods, hits


def ebay_asks(title, limit=100):
    """Live fixed-price asks. Returns (rows, total) or (None, err)."""
    q = urllib.parse.urlencode({'q': title, 'limit': min(limit, 200),
                                'filter': 'buyingOptions:{FIXED_PRICE}'})
    try:
        d = EB.get('https://api.ebay.com/buy/browse/v1/item_summary/search?' + q, EB.token())
    except urllib.error.HTTPError as e:
        return None, f'HTTP {e.code}'
    rows = []
    for it in d.get('itemSummaries') or []:
        try:
            rows.append((float(it['price']['value']), it.get('title', ''), it.get('itemWebUrl', '')))
        except (KeyError, TypeError, ValueError):
            continue
    return rows, d.get('total')


def relevant(t, card, number, parallels):
    """Is this eBay title plausibly the same card?

    Without this the statistics are meaningless. A raw search for the Flagg Blue
    Refractor returned an $8 Bilal Coulibaly and a $45,000 outlier, which between
    them moved the median from $1,030 to $2,100 and flipped the verdict.

    Three tests, in order of how much damage they prevent:
      surname  a different player is a different card, full stop
      number   a conflicting card number is a different card; a MISSING one is
               not held against the listing, because sellers omit it constantly
      parallel every finish/colour word we name must appear
    """
    tl = t.lower()
    if card and card not in tl:
        return False
    if number:
        import re as _re
        flat = _re.sub(r'[^a-z0-9]', '', number)
        found = [_re.sub(r'[^a-z0-9]', '', m) for m in _re.findall(r'#\s*([a-z0-9][a-z0-9\-]*)', tl)]
        if found and flat not in found:
            return False
    if not all(w in tl for w in parallels):
        return False
    # ...and nothing EXTRA. "Blue RayWave Refractor" contains every word of "Blue
    # Refractor" and is a different, dearer card; a one-directional test lets it
    # in and drags the median up by hundreds. Same asymmetry that mispriced the
    # Gold vs "Gold Interstellar" parallels in scp-comps.
    extra = [w for w in (FINISHES + COLOURS) if w in tl and w not in parallels]
    # 'refractor' inside 'x-fractor' etc. is handled by requiring a word boundary
    import re as _re
    extra = [w for w in extra if _re.search(r'(?<![a-z])' + _re.escape(w) + r'(?![a-z])', tl)]
    if extra:
        return False
    return True


def trimmed(vals, lo_pct=10, hi_pct=90):
    """Drop the extremes before describing a distribution. One aspirational
    $45,000 ask should not decide whether a guide price is credible."""
    if len(vals) < 5:
        return vals
    lo = int(len(vals) * lo_pct / 100.0)
    hi = int(round(len(vals) * hi_pct / 100.0))
    return vals[lo:hi] or vals


def pct(sorted_vals, p):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, int(round((p / 100.0) * (len(sorted_vals) - 1))))
    return sorted_vals[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('card')
    ap.add_argument('--price', type=float, help="the asking price you were alerted about")
    ap.add_argument('--all', action='store_true', help='show every SCP product returned')
    a = ap.parse_args()

    print(f'CARD   {a.card}\n')

    prods, hits = scp_lookup(a.card, a.all)
    if a.all:
        print(f'SportsCardsPro returned {len(prods)} products; {len(hits)} matched:')
        for p in prods[:30]:
            ok = SCP.scp_matches(p, a.card)[0]
            print(f"  {'MATCH' if ok else '     '} {p.get('console-name','')} | {p.get('product-name','')}")
        print()

    guide = None
    pick = SCP.best(hits, a.card) if hits else None
    if pick is not None:
        p = pick
        guide = money(p.get('loose-price'))
        print(f"GUIDE  {p.get('console-name','')} | {p.get('product-name','')}")
        parts = [f'{lbl} ${money(p.get(f)):,.2f}' for lbl, f in GRADES if money(p.get(f))]
        print('       ' + '   '.join(parts))
        vol = SCP.volume(p.get('sales-volume'))
        print(f'       built from {vol} recorded sales'
              + ('   <-- THIN, treat as anecdote' if (vol or 0) < 3 else ''))
    elif not hits:
        print(f'GUIDE  no confident SportsCardsPro match ({len(prods)} candidates).'
              '  Re-run with --all to see them.')
    else:
        print(f'GUIDE  {len(hits)} products matched — ambiguous, so no guide price.'
              '  Re-run with --all.')
        for h in hits[:5]:
            print(f"         {h.get('console-name','')} | {h.get('product-name','')}")
    print()

    rows, total = ebay_asks(a.card)
    if rows is None:
        print(f'EBAY   lookup failed: {total}')
        return 1
    if not rows:
        print('EBAY   no live fixed-price listings matched that search.')
        return 0

    # Narrow to listings that are actually this card before believing any number.
    import re as _re
    facts = SCP.CT.card_facts(a.card)
    number = (facts.get('number') or '').lower() or None
    surname = None
    if hits:
        who = _re.split(r'[\[#]', hits[0].get('product-name') or '')[0].strip()
        parts = [w for w in _re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", who)]
        surname = parts[-1].lower() if parts else None
    parallels = sorted(SCP.parallel_terms(a.card.partition('#')[2]))
    kept = [r for r in rows if relevant(r[1], surname, number, parallels)]
    if not kept:
        print(f'EBAY   {len(rows)} results, but none matched this exact card '
              f'(player {surname!r}, #{number}, {parallels or "base"}).')
        print('       Widen the search text or check the parallel name.')
        return 0

    vals_all = sorted(r[0] for r in kept)
    vals = trimmed(vals_all)
    lo, med, hi = vals[0], statistics.median(vals), vals[-1]
    p75 = pct(vals, 75)
    print(f'EBAY   {total} results for that text; {len(kept)} are this card '
          f'(player, number and parallel all match).')
    print('       These are ASKS, not sales — an upper bound on value, never a floor.')
    print(f'       low ${lo:,.2f}   median ${med:,.2f}   75th ${p75:,.2f}   high ${hi:,.2f}'
          + (f'   [trimmed from {len(vals_all)}]' if len(vals) != len(vals_all) else ''))
    rows = kept

    # Which parallels are actually in these results?
    seen = {}
    for _, t, _u in rows:
        tl = t.lower()
        words = [w for w in COLOURS if w in tl] + [w for w in FINISHES if w in tl]
        if words:
            seen[' '.join(sorted(set(words)))] = seen.get(' '.join(sorted(set(words))), 0) + 1
    if len(seen) > 1:
        print('\n       Parallels present in these results — check you are pricing the same one:')
        for k, n in sorted(seen.items(), key=lambda x: -x[1])[:6]:
            print(f'         {n:>3}x  {k}')

    print('\n       Cheapest five:')
    for v, t, u in sorted(rows)[:5]:
        print(f'         ${v:>9,.2f}  {t[:66]}')

    if guide:
        print()
        if guide > p75:
            print(f'VERDICT  Guide ${guide:,.2f} sits ABOVE the 75th percentile of live asks '
                  f'(${p75:,.2f}).')
            print('         A card cannot sell for more than everyone is asking. The guide is')
            print('         stale — most likely a current release whose price has fallen since.')
            print('         Any "saving" measured against it is not real.')
        elif guide > med:
            print(f'VERDICT  Guide ${guide:,.2f} is above the median ask ${med:,.2f}. Plausible')
            print('         but soft; sanity-check the cheapest listings above before acting.')
        else:
            print(f'VERDICT  Guide ${guide:,.2f} sits within the live ask range. Reasonable baseline.')

    if a.price:
        print()
        print(f'YOUR LISTING  ${a.price:,.2f}')
        if guide:
            print(f'   vs guide   {a.price - guide:+,.2f}  (what the alert is claiming)')
        print(f'   vs median ask  {a.price - med:+,.2f}   <-- the number that matters')
        cheaper = sum(1 for v in vals_all if v < a.price)
        print(f'   {cheaper} of {len(vals_all)} matching live listings are cheaper than this.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
