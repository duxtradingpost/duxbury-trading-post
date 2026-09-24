#!/usr/bin/env python3
"""Turn raw eBay sold rows into a defensible comp, and record it.

    python3 comp-tools.py query  "<card title>"      # build the search string
    python3 comp-tools.py judge  "<card title>" [--sku S] [--source NAME] < rows.txt
    python3 comp-tools.py terapeak "<card title>" [--sku S] < summary.txt
    python3 comp-tools.py sheet                      # write comp-queue.csv to fill in
    python3 comp-tools.py ingest                     # read it back and record
    python3 comp-tools.py status

Rows on stdin are one per line, "$PRICE :: listing title" — the shape scraped
off an eBay sold-listings page.

Why this exists as code rather than judgement in the moment. On 8 September the
hand-built comp file had base-card prices sitting against numbered parallels:
a $202 PSA 10 Meteoric Rise carried a "$4-6" comp because the search swept up
raw Mojo refractors. eBay search mixes grades, parallels and base cards freely,
so the filtering has to be explicit and repeatable or it silently poisons every
price downstream.

Results go to comp-verified.json, deliberately separate from the 27 August
comp-data.json so machine-gathered comps can always be told apart from the
hand-built set, and so a bad batch can be dropped without losing the old work.

Multiple sources are kept per card under `sources`, and the top-level lo/hi/
median is the consensus across them. Sources that disagree by more than 25% are
flagged rather than averaged — divergence usually means one of them matched the
wrong card, and quietly splitting the difference would bury that.

Known sources:
  terapeak   eBay's own transaction records, via Seller Hub > Research > Product
             research. PREFERRED. Its category/condition/GRADE/grader filters do
             properly what the title-matching rules below only approximate, and
             it is the sole source of SELL-THROUGH — the share of listings that
             actually sold, which answers "why is this not moving" rather than
             "what is it worth". Free with the eBay Store subscription; no API
             approval needed. Paste the summary block into stdin.
  ebay-sold  eBay completed listings, scraped from public search. Raw and graded
             mixed together, last ~90 days, needs every filter below.
  psa-apr    psacard.com/auctionprices/search?q=... — PSA-GRADED ONLY, but
             aggregates eBay, Goldin, Heritage and others and goes back years.
             Use it for a graded anchor, and to establish that a card does not
             trade at all: if APR has no entry for the parallel, no graded copy
             has ever sold.
"""
import json, os, re, statistics, sys
from datetime import date

HERE     = os.path.dirname(os.path.abspath(__file__))
VERIFIED = os.path.join(HERE, 'comp-verified.json')
LEGACY   = os.path.join(HERE, 'comp-data.json')

GRADERS   = ('psa', 'bgs', 'sgc', 'cgc')
MIN_N     = 3          # below this it is an anecdote, not a comp
DIVERGE   = 0.25       # sources further apart than this are flagged, not averaged
DIVERGE_MIN = 5.00     # ...but only if the gap is worth real money. A 2017 Tom
                       # Brady base at $2.00 against $2.75 is 27% apart and
                       # seventy-five cents; flagging it teaches you to ignore
                       # the flag.
WIDE      = 3.0        # hi/lo beyond this is a bad match set, not a price range
STOP      = {'the','and','rc','of','a'}


HELD_TAGS = ('Personal', 'At PSA')


def _is_personal(row):
    """Not sellable right now — skip for posting, repricing and mispricing flags.

    Two distinct cases, both held back:
      `Personal`  Craig's own collection. An owner draw, excluded from COGS.
      `At PSA`    business stock out for grading. It comes back and gets sold.

    The marker is the TAG. It used to be a $9,999 placeholder price, which four
    scripts each had to remember; one forgetting it would put a personal card in
    the Instagram pool or the repricing list. The price test stays as a fallback
    until the placeholders are repriced. The website shows these in its own
    "Personal Collection" section off the `coming-soon` Shopify collection, so
    they are deliberately quantity 0 and carry no price to buyers."""
    tags = [t.strip() for t in (row.get('Tags') or '').split(',')]
    if any(t in HELD_TAGS for t in tags):
        return True
    try:
        return float(row.get('Variant Price') or 0) >= 9000
    except (TypeError, ValueError):
        return False


def card_facts(title):
    """Pull the identity out of a card title: what a comp MUST also have."""
    t = title.lower()
    return {
        'run':    (re.search(r'/(\d+)\b', t) or [None, None])[1],       # /25
        'number': (re.search(r'#([a-z0-9\-]+)', t) or [None, None])[1], # #TA-PT
        'grade':  next((f'{g} {m.group(1)}' for g in GRADERS
                        for m in [re.search(rf'{g}\s*(10|9\.5|9|8|7)\b', t)] if m), None),
        'graded': any(g in t for g in GRADERS),
        'year':   (re.search(r'\b(19|20)\d{2}\b', t) or [None])[0],
        'words':  [w for w in re.findall(r'[a-z]{3,}', t) if w not in STOP],
    }


def query_for(title):
    """A search string built from the distinguishing tokens, not the whole title.

    Whole titles return nothing; two words return everything. The middle is the
    player, the set, the parallel and the print run."""
    f = card_facts(title)
    drop = {'auto','rookie','card','sports','trading'}
    words = [w for w in f['words'] if w not in drop][:8]
    q = ' '.join(words)
    if f['run']:
        q += f" /{f['run']}"
    if f['grade']:
        q += ' ' + f['grade'].upper()
    return q


def matches(card, row_title):
    """Does this sold listing plausibly describe the same card?"""
    r = row_title.lower()
    if card['run'] and f"/{card['run']}" not in r and f"of {card['run']}" not in r:
        return False, f"no /{card['run']}"
    # The reverse also matters: if OUR card carries no print run, a row that does
    # is a numbered parallel, which is a different and usually dearer card. A
    # Green /99 and a Gold 29/50 were both being counted as comps for a base auto.
    if not card['run'] and re.search(r'\b\d{1,3}\s*/\s*\d{1,4}\b|/\d{1,4}\b', r):
        return False, 'row is a numbered parallel, ours is not'
    # The card number is the single most decisive identifier: BCP-22 and BCP-167
    # are different cards at different prices, and every other word in the title
    # is identical. Only enforced when the number is distinctive enough to mean
    # something — a bare '#4' matches too much to be evidence.
    num = card['number']
    if num and len(num) >= 3:
        # Reject on a CONFLICTING number, never on a missing one. Plenty of
        # sellers omit it entirely — four of seven genuine Ja'Marr Chase /99
        # sales had no "#PP-21" in the title and were being thrown away, leaving
        # a comp built from the two priciest listings. But a row that names a
        # DIFFERENT card (#58 when ours is #PP-21) is a different card.
        # Numbers are compared with separators stripped: #SS-2 == #SS2.
        flat = re.sub(r'[^a-z0-9]', '', num)
        found = [re.sub(r'[^a-z0-9]', '', m) for m in re.findall(r'#([a-z0-9][a-z0-9\-]*)', r)]
        if found and flat not in found:
            return False, f'names #{found[0].upper()}, ours is #{num.upper()}'
    if card['grade']:
        g, n = card['grade'].split()
        if not re.search(rf'{g}\s*{re.escape(n)}\b', r):
            return False, f'not {card["grade"].upper()}'
    elif any(g in r for g in GRADERS):
        return False, 'graded, ours is raw'
    if card['year'] and card['year'] not in r:
        return False, 'year differs'
    # the rarest few words of our title should appear — this is what keeps base
    # cards and the wrong parallel out
    key = [w for w in card['words'] if len(w) > 4][:6]
    hits = sum(1 for w in key if w in r)
    # Half the words is not enough when a card only HAS three distinctive words:
    # a Billboard Material insert shares "topps" and "james" with a Struttin'
    # case hit and sailed through on two of three. Demand all of them when the
    # title is short, and all-but-one when it is long enough to absorb a typo.
    need = len(key) if len(key) <= 3 else len(key) - 1
    if key and hits < need:
        return False, 'too few matching words'
    return True, ''


def judge(title, rows):
    card = card_facts(title)
    kept, rejected = [], []
    for price, rtitle in rows:
        ok, why = matches(card, rtitle)
        (kept if ok else rejected).append((price, rtitle, why))
    prices = sorted(p for p, _, _ in kept)
    if not prices:
        return {'n': 0, 'verdict': 'no usable comps', 'rejected': len(rejected)}
    # drop a single wild outlier before measuring the range
    if len(prices) >= 5:
        med = statistics.median(prices)
        prices = [p for p in prices if 0.25 * med <= p <= 4 * med]
    lo, hi = min(prices), max(prices)
    out = {'lo': round(lo, 2), 'hi': round(hi, 2),
           'median': round(statistics.median(prices), 2), 'n': len(prices),
           'rejected': len(rejected)}
    if len(prices) < MIN_N:
        out['verdict'] = f'thin — only {len(prices)} sale(s), treat as indicative'
    elif lo > 0 and hi / lo > WIDE:
        out['verdict'] = f'spread {hi/lo:.1f}x — still mixing something, re-query'
    else:
        out['verdict'] = 'usable'
    return out


def consensus(entry):
    """Roll per-source figures into one view.

    The median is the median of source medians. The RANGE deliberately prefers
    sources whose range is not flagged wide: Terapeak reports the full spread of
    everything in the category, which for the Golden was $350-$1,424 because
    Trading Card Singles still sweeps in lots and other parallels. Its average is
    excellent; its range is not a range for one card."""
    src = entry.get('sources', {})
    if not src:
        return entry
    meds = [d['median'] for d in src.values()]
    entry['median'] = round(statistics.median(meds), 2)
    narrow = [d for d in src.values() if not d.get('range_wide')]
    use = narrow or list(src.values())
    entry['lo'] = round(min(d['lo'] for d in use), 2)
    entry['hi'] = round(max(d['hi'] for d in use), 2)
    entry['n'] = sum(d.get('n', 0) for d in src.values())
    entry['date'] = date.today().isoformat()
    st = [d['sell_through'] for d in src.values() if d.get('sell_through') is not None]
    if st:
        entry['sell_through'] = st[0]
    if (len(meds) > 1 and min(meds) > 0
            and (max(meds) - min(meds)) / min(meds) > DIVERGE
            and (max(meds) - min(meds)) >= DIVERGE_MIN):
        entry['verdict'] = 'SOURCES DISAGREE: ' + ', '.join(
            f'{k} ${d["median"]:.0f}' for k, d in src.items())
    else:
        entry['verdict'] = 'usable'
    return entry


def load(path):
    """Entries recorded before multi-source support carry a flat `source` key
    instead of a `sources` dict. Fold those in on read, or a later source
    silently replaces the earlier one instead of cross-referencing it."""
    try:
        data = json.load(open(path))
    except Exception:
        return []
    for e in data:
        if 'sources' not in e and e.get('source'):
            e['sources'] = {e.pop('source'): {
                k: e[k] for k in ('lo', 'hi', 'median', 'n', 'rejected', 'rows_seen')
                if k in e}}
    return data


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]

    if cmd == 'query':
        print(query_for(sys.argv[2]))
        return

    if cmd == 'sheet':
        # Craig can comp a card faster by eye than any filter can — he knows at a
        # glance that #281 is not #411. This exists so that knowledge goes in
        # directly instead of being approximated. Open in Excel, type the market
        # price, save, then `ingest`.
        import csv as _csv
        comps = {}
        for f in (LEGACY, VERIFIED):
            try:
                for c in json.load(open(f)):
                    if c.get('lo') not in (None, ''):
                        comps[c['title']] = c
            except Exception:
                pass
        ver = {c['title'] for c in load(VERIFIED)}
        exp = None
        import glob as _glob
        cands = _glob.glob(os.path.join(HERE, 'products_export*.csv'))
        if cands:
            exp = max(cands, key=os.path.getmtime)
        rows, seen = [], set()
        for r in _csv.DictReader(open(exp)):
            h = (r.get('Handle') or '').strip()
            t = (r.get('Title') or '').strip()
            if not h or h in seen or r.get('Status') != 'active':
                continue
            seen.add(h)
            sku = (r.get('Variant SKU') or '').strip()
            if sku.split('-')[0] == 'Boxes':
                continue
            try:
                price = float(r.get('Variant Price') or 0)
                cost = float(r.get('Cost per item') or 0)
            except ValueError:
                continue
            if cost <= 0 or price <= 0 or _is_personal(r) or t in ver:
                continue
            rows.append({'Card': t, 'SKU': sku, 'Your ask': f'{price:.2f}',
                         'Cost': f'{cost:.2f}',
                         'Old comp': (f"{comps[t]['lo']:.0f}-{comps[t]['hi']:.0f}"
                                      if t in comps else ''),
                         'MARKET PRICE': '', 'How many sales': '', 'Notes': ''})
        rows.sort(key=lambda x: -float(x['Your ask']))
        dest = os.path.join(HERE, 'comp-queue.csv')
        with open(dest, 'w', newline='') as fh:
            w = _csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f'{len(rows)} cards -> {dest}')
        print('Fill in MARKET PRICE (and How many sales, if you like), save, then:')
        print('  python3 comp-tools.py ingest')
        return

    if cmd == 'ingest':
        import csv as _csv
        src = os.path.join(HERE, 'comp-queue.csv')
        if not os.path.exists(src):
            sys.exit('no comp-queue.csv — run: comp-tools.py sheet')
        v = load(VERIFIED)
        added = 0
        for r in _csv.DictReader(open(src)):
            raw = (r.get('MARKET PRICE') or '').strip().replace('$', '').replace(',', '')
            if not raw:
                continue
            try:
                m = float(raw)
            except ValueError:
                print(f"  skipped, not a number: {raw!r}  {r['Card'][:40]}")
                continue
            try:
                n = int((r.get('How many sales') or '0').strip() or 0)
            except ValueError:
                n = 0
            e = next((x for x in v if x.get('title') == r['Card']), None)
            if e is None:
                e = {'title': r['Card'], 'sku': r.get('SKU', ''), 'sources': {}}
                v.append(e)
            e['sources']['craig'] = {'lo': m, 'hi': m, 'median': m, 'n': n or 1,
                                     'date': date.today().isoformat()}
            # Craig's own number OVERRIDES, it does not average. Most cards in
            # the queue are there precisely because their scraped/guide comp is
            # wrong for the card — rolling his $120 together with a bad $6.99
            # guide match gave lo 6.99 / hi 120 / median 63.50 and a 17x spread
            # that WIDE_COMP then threw away. He is looking at the real sales.
            # Other sources stay recorded under `sources` for reference.
            if 'craig' in e['sources']:
                c = e['sources']['craig']
                e['median'], e['lo'], e['hi'], e['n'] = c['median'], c['lo'], c['hi'], c['n']
            else:
                meds = [d['median'] for d in e['sources'].values()]
                e['median'] = round(statistics.median(meds), 2)
                e['lo'] = round(min(d['lo'] for d in e['sources'].values()), 2)
                e['hi'] = round(max(d['hi'] for d in e['sources'].values()), 2)
                e['n'] = sum(d['n'] for d in e['sources'].values())
            e['date'] = date.today().isoformat()
            e['verdict'] = 'usable'
            if (r.get('Notes') or '').strip():
                e['note'] = r['Notes'].strip()
            added += 1
        json.dump(v, open(VERIFIED, 'w'), indent=1)
        print(f'{added} comp(s) recorded from your sheet · {len(v)} total')
        return

    if cmd == 'terapeak':
        # Terapeak has already filtered by category, condition and grade, so there
        # is nothing here to match on — just read its numbers. Its price RANGE is
        # not trustworthy as lo/hi: for the Golden it spanned $350-$1,424 because
        # Trading Card Singles still sweeps in lots and other parallels. The
        # average is the signal; the range is recorded but marked wide.
        title = sys.argv[2]
        sku = sys.argv[sys.argv.index('--sku') + 1] if '--sku' in sys.argv else ''
        blob = sys.stdin.read()
        def grab(label, pat=r'\$?([\d,]+\.?\d*)'):
            m = re.search(pat + r'\s*%?\s*\n\s*' + label, blob, re.I)
            return float(m.group(1).replace(',', '')) if m else None
        avg = grab('Avg sold price')
        rng = re.search(r'\$([\d,]+\.?\d*)\s*-\s*\$([\d,]+\.?\d*)\s*\n\s*Sold price range', blob, re.I)
        lo = float(rng.group(1).replace(',', '')) if rng else None
        hi = float(rng.group(2).replace(',', '')) if rng else None
        st = grab('Sell-through')
        sellers = grab('Total sellers')
        if avg is None:
            sys.exit('could not find "Avg sold price" — paste the whole summary block')

        wide = bool(lo and hi and lo > 0 and hi / lo > WIDE)
        rec = {'lo': lo if lo is not None else avg, 'hi': hi if hi is not None else avg,
               'median': avg, 'n': int(sellers or 0), 'sell_through': st,
               'range_wide': wide, 'date': date.today().isoformat()}
        print(json.dumps({**rec, 'title': title}, indent=1))
        if wide:
            print(f'note: price range ${lo:.0f}-${hi:.0f} is {hi/lo:.1f}x — the average is '
                  f'the usable number, the range is mixing card types')

        v = load(VERIFIED)
        e = next((x for x in v if x.get('title') == title), None)
        if e is None:
            e = {'title': title, 'sku': sku, 'sources': {}}
            v.append(e)
        if sku:
            e['sku'] = sku
        e.setdefault('sources', {})['terapeak'] = rec
        consensus(e)
        json.dump(v, open(VERIFIED, 'w'), indent=1)
        print(f"-> recorded (terapeak); {len(e['sources'])} source(s)")
        print(f"   consensus ${e['lo']:.0f}-${e['hi']:.0f} median ${e['median']:.0f}"
              + (f" · sell-through {st:.0f}%" if st is not None else '')
              + f" · {e['verdict']}")
        return

    if cmd == 'status':
        v = load(VERIFIED)
        print(f'{len(v)} verified comps in {os.path.basename(VERIFIED)}')
        for e in sorted(v, key=lambda x: -x.get('median', 0))[:12]:
            src = ','.join(e.get('sources', {}).keys()) or e.get('source', '?')
            warn = '  !! ' + e['verdict'] if str(e.get('verdict','')).startswith('SOURCES') else ''
            print(f"  ${e.get('lo',0):>6.0f}-{e.get('hi',0):<6.0f} med ${e.get('median',0):>6.0f} "
                  f"n={e.get('n',0):<3} [{src}] {e['title'][:44]}{warn}")
        return

    if cmd == 'judge':
        title = sys.argv[2]
        sku = ''
        if '--sku' in sys.argv:
            sku = sys.argv[sys.argv.index('--sku') + 1]
        source = 'ebay-sold'
        if '--source' in sys.argv:
            source = sys.argv[sys.argv.index('--source') + 1]
        rows = []
        for line in sys.stdin:
            m = re.match(r'\s*\$([\d,]+\.?\d*)\s*::\s*(.+)', line)
            if m:
                rows.append((float(m.group(1).replace(',', '')), m.group(2).strip()))
        res = judge(title, rows)
        res.update({'source': source, 'rows_seen': len(rows)})
        print(json.dumps(res, indent=1))
        if not (res.get('n', 0) and res['verdict'] == 'usable'):
            print('-> NOT recorded; fix the query and try again')
            return

        v = load(VERIFIED)
        entry = next((e for e in v if e.get('title') == title), None)
        if entry is None:
            entry = {'title': title, 'sku': sku, 'sources': {}}
            v.append(entry)
        entry.setdefault('sources', {})[source] = {
            k: res[k] for k in ('lo', 'hi', 'median', 'n', 'rejected', 'rows_seen')}
        entry['sources'][source]['date'] = date.today().isoformat()
        entry['date'] = date.today().isoformat()
        if sku:
            entry['sku'] = sku

        consensus(entry)
        json.dump(v, open(VERIFIED, 'w'), indent=1)
        print(f"-> recorded ({source}); {len(entry['sources'])} source(s) for this card")
        print(f"   consensus ${entry['lo']:.0f}-{entry['hi']:.0f} median ${entry['median']:.0f} · {entry['verdict']}")
        return

    sys.exit(f'unknown command: {cmd}')


if __name__ == '__main__':
    sys.exit(main())
