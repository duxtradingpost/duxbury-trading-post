#!/usr/bin/env python3
"""Price the whole catalogue against SportsCardsPro, automatically.

    python3 reports/scp-comps.py [--print] [--limit N]

This is the automated comping that eBay refused. SportsCardsPro (PriceCharting's
sports arm) returns grade-split prices — Ungraded / Grade 9 / PSA 10 — over a
token, headless, so unlike Terapeak it belongs in the 07:00 chain.

Validated before being trusted, on two cards comped by hand from eBay sold data:
  Golden #18 PSA 10   SCP $554.25  vs  our $564.19   1.8% apart
  Achane #10 ungraded SCP $297.18  vs  our $297.00   0.06% apart

Three rules learned the hard way and enforced below:

1. NEVER trust their ranking. `/api/product` (singular, "best match") returned a
   Marvel Deadpool sketch for "Matthew Golden Downtown" and a Funko POP for
   "Drake Maye". This uses `/api/products` (plural), which returns every
   candidate, and then picks among them LOCALLY with comp-tools.py's rules —
   print run, grade, year, card number, rare words. Their search decides what we
   look at; it never decides what we believe.

2. A near-miss is worse than no match. The same card number carries four
   different Orange /25 parallels priced $25 to $300; picking the wrong one is a
   12x error stated with confidence. Where several candidates survive filtering,
   this records NOTHING and flags the card for a human. One query for
   "Matthew Golden Downtown" returns 14 products — base, Optic, Gold, Black
   Pandora, Oversized, and a Downtown Duo — spanning $15 to $2,009 ungraded.

3. The CSV price-guide endpoints are unusable and are not a rate-limit problem.
   `/price-guide/download-custom` sits behind Cloudflare and answers with an
   HTTP 403 whose body is the "Just a moment..." interstitial. An earlier version
   of this script read that 403 as SportsCardsPro's documented "1 CSV per 10
   minutes" limit and slept for it, so the launchd job ran every 15 minutes for a
   day and cached ZERO sets and priced ZERO cards while reporting success. The
   JSON API has no such wall — it is a plain 1 call/second.

Grade mapping, confirmed against a hand-built eBay-sold comp rather than assumed:
  Ungraded  loose-price          PSA 10   manual-only-price   ($554.25 on the
  Grade 9   graded-price         BGS 10   bgs-10-price         Golden, vs $564.19
  Grade 8   condition-18-price   Grade 9.5 condition-19-price  from eBay sold)
`condition-20-price` runs ~6.5x manual-only on every row inspected and is not
used — whatever it is, it is not a price anyone pays.

Prices come back as INTEGER CENTS. The CSV gave dollar strings; conflating the
two silently multiplies every comp by 100.

Writes into comp-verified.json under the source `sportscardspro`, so it
cross-references against eBay-derived comps rather than replacing them —
consensus() flags sources that disagree by more than 25% instead of averaging
them into a plausible-looking lie.
"""
import csv, glob, hashlib, importlib.util, json, os, re, sys, time
import urllib.error, urllib.parse, urllib.request

HERE      = os.path.dirname(os.path.abspath(__file__))
TOKEN_F   = os.path.expanduser('~/.dtp-sportscardpro')
VERIFIED  = os.path.join(HERE, 'comp-verified.json')
CACHE     = os.path.join(HERE, 'scp-cache')          # per-query API responses
UNMATCHED = os.path.join(HERE, 'scp-unmatched.json')
BASE      = 'https://www.sportscardspro.com'
UA        = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DTP/1.0'
PAUSE     = 1.2            # documented limit: 1 API call/second
CACHE_HOURS = 20           # their prices regenerate daily; no point re-pulling
THIN_VOLUME = 3            # below this many recorded sales, the price is anecdote


def comp_tools():
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


CT = comp_tools()


def token():
    if not os.path.exists(TOKEN_F):
        sys.exit(f'missing {TOKEN_F}')
    return open(TOKEN_F).read().strip()


def money(cents):
    """Their JSON is integer cents. None where they have no sale for that grade."""
    if cents in (None, '', 0):
        return None
    try:
        return round(int(cents) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def volume(v):
    """sales-volume arrives as a STRING ("87"), not a number. An isinstance(int)
    check on it silently marked all 38 priced cards as thin evidence."""
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


_last_call = [0.0]


def api_products(query, tok):
    """Every product SportsCardsPro thinks might be this card. Cached per query.

    Returns [] on a miss and None on a transport failure, so a network blip is
    not recorded as "this card does not exist"."""
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.sha1(query.lower().encode()).hexdigest()[:16]
    path = os.path.join(CACHE, f'q-{key}.json')
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < CACHE_HOURS * 3600:
        try:
            return json.load(open(path))['products']
        except Exception:
            pass
    wait = PAUSE - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    url = f'{BASE}/api/products?t={tok}&q={urllib.parse.quote(query)}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        # A Cloudflare challenge is HTML, not JSON, and means the endpoint is
        # walled off — not that we asked too fast. Say which it is.
        blob = e.read()[:300].decode('utf-8', 'replace')
        kind = 'Cloudflare challenge' if 'Just a moment' in blob else blob[:120]
        print(f'  HTTP {e.code} on /api/products: {kind}', file=sys.stderr)
        return None
    except Exception as e:
        print(f'  {type(e).__name__} on /api/products: {e}', file=sys.stderr)
        return None
    finally:
        _last_call[0] = time.time()
    prods = body.get('products') or []
    json.dump({'query': query, 'products': prods}, open(path, 'w'))
    return prods


def query_for(title):
    """The query SportsCardsPro's search actually answers.

    comp-tools' query_for is built for eBay and is wrong here twice over: it
    drops the year (its word regex is [a-z]{3,}) and it appends "/99" and "PSA
    10", none of which appear in a SportsCardsPro product name. Every one of the
    first twelve cards returned zero results.

    What works is the title up to the card number, plus the ONE word after it —
    because that word is the insert set, and the insert set is what separates
    "2025 Topps Chrome Power Players" from plain "2025 Topps Chrome":

        before #        '2025 Topps Chrome Ja'Marr Chase'        -> 100 products
        before # plus 1 '2025 Topps Chrome Ja'Marr Chase Power'  ->  12, right set first

    But that word is only the insert set when the card HAS one. Otherwise it is a
    team or a grade, and it poisons the search: "#66 Patriots" asked for
    "2017 Panini Tom Brady Patriots" and came back with 2006 Topps team sets;
    "#RPJ-THN RC" asked for "...TreVeyon Henderson RC" and came back with
    Impeccable RC Logo Patch. So this returns BOTH forms, and the caller falls
    back to the short one when the long one matches nothing. A fallback beats a
    list of every team name in three sports, and it catches noise words nobody
    thought to enumerate.
    """
    head, _, tail = title.partition('#')
    words = tail.split()
    long = f"{head.strip()} {words[1]}".strip() if len(words) > 1 else head.strip()
    return long, head.strip()


# Colours and finishes. SportsCardsPro names a parallel in brackets — "[Pink
# Refractor]" — and never states a print run, so comp-tools' "/99 must appear"
# rule rejects every row it is given. This vocabulary is what stands in for it.
PARALLEL_WORDS = {
    'red', 'orange', 'yellow', 'green', 'blue', 'purple', 'pink', 'black', 'white',
    'gold', 'silver', 'bronze', 'aqua', 'teal', 'sepia', 'magenta', 'camo', 'rose',
    'refractor', 'x-fractor', 'xfractor', 'prizm', 'wave', 'shimmer', 'mojo', 'hyper',
    'lava', 'nebula', 'pandora', 'sparkle', 'vinyl', 'atomic', 'negative', 'speckle',
    'cracked', 'ice', 'disco', 'tiger', 'zebra', 'laser', 'mini-diamond', 'die',
    'holo', 'foil', 'scope', 'velocity', 'pulsar', 'choice', 'fast', 'genesis',
    'geometric', 'logofractor', 'superfractor', 'raywave', 'sunburst', 'dragon',
    # Gem names are parallels too, and leaving them out silently collapsed three
    # distinct Omarion Hampton autos — plain, Emerald and Sapphire — into one
    # indistinguishable set.
    'emerald', 'sapphire', 'ruby', 'amethyst', 'onyx', 'jade', 'topaz', 'opal',
    'diamond', 'platinum', 'titanium', 'copper', 'carbon', 'marble', 'galactic',
}


# Team names that begin with a colour. Craig's titles end with the team, so
# "2026 Topps Tribute Payton Tolle #4 Orange /25 RC Red Sox" was read as an
# "orange red" parallel and matched nothing — the real [Orange] #4 was right
# there in the results. Plurals are safe on their own ("Reds", "Browns") because
# matching is word-boundary exact; only these two-word phrases leak a colour.
TEAM_PHRASES = ('red sox', 'blue jays', 'white sox', 'blue jackets', 'red wings',
                'red raiders', 'green bay', 'golden bears', 'silver knights',
                'black knights', 'black bears', 'orange county')


def parallel_terms(text):
    t = (text or '').lower()
    for phrase in TEAM_PHRASES:
        t = t.replace(phrase, ' ')
    return {w for w in re.findall(r'[a-z][a-z\-]*', t) if w in PARALLEL_WORDS}


# Words in their console-name that our titles routinely leave out, so their
# absence is not evidence of a different set. Craig writes "2023 Chronicles DP"
# for "2023 Panini Chronicles Draft Picks".
SET_OPTIONAL = {'panini', 'topps', 'bowman', 'cards', 'baseball', 'football',
                'basketball', 'wrestling', 'hockey', 'soccer', 'draft', 'picks',
                'update', 'series', 'the', 'and', 'of'}


def set_words(text):
    """The distinguishing words of a set name, normalised.

    'Autograph' and 'Auto' are the same thing and must not be treated as
    different sets — Craig writes "Auto", SportsCardsPro writes "Autograph"."""
    return {w for w in stems(text) if w not in SET_OPTIONAL}


def is_auto(text):
    """Autographed or not. This is categorical, never a tie-break.

    The Tetairoa McMillan Rookie Recruits AUTO /199 was priced at $1.47 off the
    non-auto insert of the same name and number, against a hand-built eBay comp
    of $65.00 — a 44x error delivered with a straight face. An auto and its base
    are different cards."""
    return bool(AUTO_RE.search((text or '').lower()))


# One idea, five spellings. SportsCardsPro writes "Autograph" INSIDE the
# parallel bracket -- "[Black Autograph]", "[Rookie Autograph]" -- where Craig
# writes "Auto" after the card number, and signature sets say neither because
# every card in them is signed. Left unnormalised this rejected the whole of
# Topps Signature Class and Panini Black on the word 'autograph'.
AUTO_RE = re.compile(r'\b(?:autographs?|auto|signatures?|sigs?)\b')


def stems(text):
    """Words, lowercased, plural 's' dropped, autograph-words folded to one.

    Plural folding is what makes "Rookie Recruits" and "Rookie Recruit" the same
    set name."""
    t = AUTO_RE.sub('auto', (text or '').lower())
    return {re.sub(r's$', '', w) for w in re.findall(r"[a-z][a-z'\-]{1,}", t)}


def scp_matches(product, title, sport=None):
    """Is this SportsCardsPro product our card? Reasons, so misses are debuggable.

    Four tests, each of which caught a real wrong answer:

    year      console-name carries it; a 2024 Chrome Maye is not a 2025 one.
    number    the single most decisive field, compared with separators stripped
              (#SS-2 == #SS2) and CONFLICT-ONLY — a row that names a different
              number is out, a row that names none is not punished for it.
    parallel  bracket words on their side vs the words after our card number on
              ours. Set equality both ways: a bare "Ja'Marr Chase #PP-21" is the
              base card and must NOT match our Green Refractor, and their
              "[X-Fractor]" must not match our "[Green Refractor]".

    Our parallel words are taken from AFTER the card number on purpose. Taken
    from the whole title, "2025 Topps Chrome Black ..." contributes 'black' from
    the SET name and the card can never match anything."""
    name    = product.get('product-name') or ''
    console = product.get('console-name') or ''
    blob    = f'{name} {console}'.lower()
    card    = CT.card_facts(title)

    if card['year'] and card['year'] not in blob:
        return False, 'year differs'

    # Their console-name starts with the sport. Ours comes from the Shopify tags.
    # Without this, "2025 Topps Chrome x Cactus Jack Jayson Tatum" matches a
    # WRESTLING card actually named "Cactus Jack" — the set name on our card is a
    # wrestler's name, and every other filter passes.
    if sport and not console.lower().startswith(f'{sport} cards'):
        return False, f'{console.split(" Cards")[0]} card, ours is {sport}'

    num = card['number']
    if num and len(num) >= 2:
        flat  = re.sub(r'[^a-z0-9]', '', num.lower())
        found = [re.sub(r'[^a-z0-9]', '', m)
                 for m in re.findall(r'#([a-z0-9][a-z0-9\-]*)', blob)]
        if found and flat not in found:
            return False, f'names #{found[0].upper()}, ours is #{num.upper()}'

    # The player. Nothing above tests it, and without it a query for the Cactus
    # Jack Jayson Tatum #1 came back with Scottie Barnes, Sheamus and Ivar all
    # surviving every other filter — same year, same card number, same
    # "[Aqua Shimmer Refractor]". Had only one survived, this would have written
    # a wrestling card's price onto a basketball card and called it verified.
    #
    # Their product-name is "<player> [<parallel>] #<num>", so the part before
    # the first bracket or hash is the name. Every word of it must appear in our
    # title — which also rejects "Donald Driver / Matthew Golden" (a Downtown Duo)
    # when ours is the Matthew Golden single.
    who = re.split(r'[\[#]', name)[0]
    missing = [w for w in re.findall(r"[a-z][a-z'\-]{2,}", who.lower())
               if w not in title.lower()]
    if missing:
        return False, f'player {who.strip()!r} (missing {missing[0]})'

    # The parallel, as a SUBSET rather than an exact match. SportsCardsPro names
    # the Topps Signature Class parallel "[Orange]" where Craig writes "Orange
    # Foil"; demanding equality threw away a card whose match was sitting right
    # there. Their words must all be ours, which still rejects "[Silver]" and
    # "[Teal]" against our Orange.
    #
    # The empty set is the trap: a bare "Baker Mayfield #50" is the BASE card and
    # is a subset of everything. If we name a parallel, they must name one too.
    if is_auto(title) != is_auto(blob):
        return False, ('their card is an auto, ours is not' if is_auto(blob)
                       else 'ours is an auto, theirs is not')

    # Every word of their bracket must appear after our card number — compared as
    # words, NOT against a fixed colour vocabulary. A vocabulary only sees the
    # words it knows, so "[Gold Interstellar]" read as plain {gold} and matched
    # our "Stars Gold /50", which is a different parallel.
    #
    # The empty bracket is the trap in the other direction: a bare "Baker
    # Mayfield #50" is the BASE card and satisfies any subset test. So if we name
    # a parallel, they must name one too.
    ours_tail = stems(title.partition('#')[2])
    theirs_br = stems(' '.join(re.findall(r'\[([^\]]*)\]', name)))
    extra = [w for w in theirs_br if w not in ours_tail]
    if extra:
        return False, f'parallel says {extra[0]!r}, our title never does'
    # If we name a colour or finish, they must name one too. Compared through the
    # vocabulary on BOTH sides, because "[Autograph]" is a non-empty bracket that
    # names no parallel at all -- it is the base auto, a different card from our
    # "[Black Autograph]", and a plain emptiness test lets it through.
    if parallel_terms(title.partition('#')[2]) and not parallel_terms(
            ' '.join(re.findall(r'\[([^\]]*)\]', name))):
        return False, 'theirs names no parallel, ours does'
    return True, ''


def rank(product, title):
    """How good a surviving candidate is. Lower is better; used only to break
    ties, never to reject.

    Set-word coverage was briefly a hard filter and it cost three priced cards
    outright: "Stars in the Night" was rejected because Craig writes "Stars" and
    never writes "in". As a tie-breaker it does the job it was added for —
    separating plain "2026 Topps Tribute" from "Tribute Autograph" — without
    turning a near-miss into a no-match."""
    name    = product.get('product-name') or ''
    console = product.get('console-name') or ''
    theirs  = parallel_terms(' '.join(re.findall(r'\[([^\]]*)\]', name)))
    ours    = parallel_terms(title.partition('#')[2])
    strip   = lambda t: re.sub(r'\b(19|20)\d{2}\b', ' ', t)
    ours_all = set_words(strip(title))
    unsaid   = sum(1 for w in set_words(strip(console)) if w not in ours_all)
    return (0 if theirs == ours else 1, unsaid)


def best(cands, title):
    """The single best candidate, or None if the top score is shared.

    A tie is still recorded as nothing. Ranking is here to resolve near-misses
    that were always the same card described two ways — not to pick a winner
    between two genuinely different parallels."""
    if len(cands) == 1:
        return cands[0]
    scored = sorted((rank(c, title), i, c) for i, c in enumerate(cands))
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][2]


def candidates(products, title, sport=None):
    """Products that could be this card. Empty is a fine answer."""
    out = []
    for p in products:
        ok, _ = scp_matches(p, title, sport)
        if ok:
            out.append(p)
    return out


def price_for(product, title):
    """The price for the grade this card actually is. None rather than a guess."""
    t = title.lower()
    if re.search(r'\bbgs\s*10\b', t):
        field = 'bgs-10-price'
    elif re.search(r'\b(psa|bgs|sgc|cgc)\s*10\b', t):
        field = 'manual-only-price'
    elif re.search(r'\b(psa|bgs|sgc|cgc)\s*9\.5\b', t):
        field = 'condition-19-price'
    elif re.search(r'\b(psa|bgs|sgc|cgc)\s*9\b', t):
        field = 'graded-price'
    elif re.search(r'\b(psa|bgs|sgc|cgc)\s*8\b', t):
        field = 'condition-18-price'
    elif re.search(r'\b(psa|bgs|sgc|cgc)\s*7\b', t):
        field = 'condition-17-price'
    else:
        field = 'loose-price'
    return money(product.get(field)), field



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


def main():
    tok = token()
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
    # --status lets the same matcher price the bin. The 107 Shopify DRAFTS are
    # the bulk/bin cards (106 of 107 under $25) and they are already digitised,
    # so valuing them needs no re-entry and none of SportsCardsPro's own lot
    # tool — which cannot price a numbered parallel anyway, its catalogue
    # carries no print runs. Default stays 'active' so the hourly job is unchanged.
    want = (sys.argv[sys.argv.index('--status') + 1]
            if '--status' in sys.argv else 'active')
    wanted = set(x.strip() for x in want.split(',') if x.strip())
    exp = max(glob.glob(os.path.join(HERE, 'products_export*.csv')), key=os.path.getmtime)
    cards, seen = [], set()
    for r in csv.DictReader(open(exp)):
        t = (r.get('Title') or '').strip()
        if r.get('Status') not in wanted or not t or t in seen:
            continue
        seen.add(t)
        try:
            price = float(r.get('Variant Price') or 0)
        except ValueError:
            continue
        if price <= 0 or _is_personal(r):
            continue
        tags = r.get('Tags') or ''
        sport = ('baseball' if 'Baseball' in tags else
                 'basketball' if 'Basketball' in tags else
                 'football' if 'Football' in tags else None)
        cards.append({'title': t, 'sku': r.get('Variant SKU', ''), 'sport': sport})
    if limit:
        cards = cards[:limit]

    recorded, ambiguous, nomatch, failed = 0, [], [], []
    v = CT.load(VERIFIED)

    # Drop every previous sportscardspro price before re-deriving them. This
    # file is a cache of what the CURRENT matcher believes, not a log of what it
    # once believed. Without this, improving the matcher cannot fix a bad comp:
    # the run that stops matching a card leaves the old wrong price sitting
    # there untouched. The Tetairoa McMillan kept its $1.47 — priced off the
    # non-auto insert, against a $65.00 eBay comp — through two rounds of fixes
    # that had already stopped matching it at all.
    #
    # Only this source is cleared. eBay-sold and Terapeak comps are hand-built
    # and are the ground truth this is checked against.
    for e in v:
        e.get('sources', {}).pop('sportscardspro', None)
    v = [e for e in v if e.get('sources')]
    for c in cards:
        long_q, short_q = query_for(c['title'])
        prods = api_products(long_q, tok)
        if prods is None:
            failed.append(c['title'])
            continue
        hits = candidates(prods, c['title'], c.get('sport'))
        query = long_q
        if not hits and short_q and short_q != long_q:
            alt = api_products(short_q, tok)
            if alt:
                hits, query = candidates(alt, c['title'], c.get('sport')), short_q
        if not hits:
            nomatch.append(f"{c['title']}  [q: {query}]")
            continue
        h = best(hits, c['title'])
        if h is None:
            # Four Orange /25 parallels priced $25-$300 share a card number. A
            # confident wrong answer is worse than none.
            ambiguous.append({'title': c['title'],
                              'options': [f"{x.get('console-name','')} | {x.get('product-name','')}"[:90]
                                          for x in hits[:5]]})
            continue
        price, field = price_for(h, c['title'])
        if price is None:
            nomatch.append(f"{c['title']}  (no {field} recorded)")
            continue
        e = next((x for x in v if x.get('title') == c['title']), None)
        if e is None:
            e = {'title': c['title'], 'sku': c['sku'], 'sources': {}}
            v.append(e)
        # sales-volume is how many sales the price is built from. A "market
        # price" derived from one sale is not a market price — the Daniel Jones
        # Neon Pink Die Cut came back at $5.35 off a single transaction. Record
        # it, but mark it thin so nothing downstream reprices a card on it.
        vol = volume(h.get('sales-volume'))
        e.setdefault('sources', {})['sportscardspro'] = {
            'lo': price, 'hi': price, 'median': price, 'n': 1,
            'matched': f"{h.get('console-name','')} | {h.get('product-name','')}"[:90],
            'grade_field': field,
            'volume': vol,
            'thin': vol is None or vol < THIN_VOLUME,
            'date': __import__('datetime').date.today().isoformat()}
        CT.consensus(e)
        recorded += 1

    for e in v:
        CT.consensus(e)          # entries that just lost their SCP price need it back
    json.dump(v, open(VERIFIED, 'w'), indent=1)
    json.dump({'ambiguous': ambiguous, 'no_match': nomatch[:60], 'failed': failed[:20]},
              open(UNMATCHED, 'w'), indent=1)
    thin = sum(1 for e in v if (e.get('sources', {}).get('sportscardspro') or {}).get('thin'))
    print(f'{len(cards)} {want} cards · {recorded} priced ({thin} on thin volume) · '
          f'{len(ambiguous)} ambiguous · {len(nomatch)} no match · {len(failed)} request failed')
    if '--print' in sys.argv:
        for a in ambiguous[:8]:
            print(f"  AMBIGUOUS  {a['title'][:52]}")
            for o in a['options']:
                print(f"             -> {o}")
        for n in nomatch[:8]:
            print(f"  NO MATCH   {n[:100]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
