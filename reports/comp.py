#!/usr/bin/env python3
"""Should we buy this card? Answers ONLY from eBay SOLD data, never from a guide.

    python3 reports/comp.py <ebay url or item id>        # step 1 - facts + what to search
    python3 reports/comp.py <url> --sold sold.json       # step 2 - filter, comp, verdict

Why this exists
---------------
On 2026-09-15 four buy/pass calls were made off the SportsCardsPro guide and
live ASKING prices. Every one was wrong, in the same direction:

    Shaq N-Tense raw      guide $200.63   real $176.50    +14%
    Dart Downtown PSA 9   guide $2,416    real $1,314     +84%
    Valdez /499 raw       guide $173.35   real $125.00   +100%
    Cam Ward BGS 9.5      guide $653      real $257      +154%

Craig bought the Valdez on that advice and it is ~$24 underwater. He nearly
bought the Dart, which would have been -$494. There is no stable correction
factor, and no price floor below which the guide is safe - the Valdez was $125.

The second half of the failure compounded the first: the supporting argument was
always ASKS ("cheapest of 12 live listings", "a PSA 9 asking less than the PSA
8"). An ask is an upper bound and never a floor. **When a guide and a board of
asks agree, that is not corroboration - they are the same kind of evidence.**

So this tool takes exactly one kind of evidence: completed sales.

Why two steps
-------------
Sold data cannot be reached headlessly. Tested 2026-09-15:

    Marketplace Insights   token refused, invalid_scope (Limited Release)
    Finding API            HTTP 418 - eBay retired findCompletedItems
    scraping /sch + LH_Sold  HTTP 403 to any User-Agent

It IS reachable through Craig's signed-in browser. So step 1 prints the search
to open and the extractor to run; step 2 does the filtering and the maths on
what comes back. The split is the point: **there is no code path that produces a
verdict without sold rows.**

Filtering is the whole game
---------------------------
On the McMillan Sapphire #326 PSA 10, the raw search returned four rows that
looked like comps and were not: $365 was "23/25" (a /25 parallel), $358 was
"RED /5 PSA 8", $49 was a "Variation SP". Unfiltered they give a median near
$200 on an $86 card, which turns a 3x overpay into a fair buy. Six hard filters
below, each categorical - a near-miss is worse than no match.
"""
import argparse, http.server, json, os, re, socketserver, statistics, subprocess, sys, threading, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))

FVF, PER_ORDER = 0.1325, 0.40          # eBay final value fee, per-order fee

# THE BUYER PAYS SHIPPING as of 2026-09-21 - free shipping was removed store-wide
# and the catalogue split across two policies. Until 2026-09-22 this file modelled
# the OLD world: it subtracted postage from the seller and counted no shipping
# revenue at all, which overstated break-even on every card. Two separate errors:
#
#   * postage was $4.90; the real Ground Advantage label costs $6.07
#     (daily-briefing.py had it right, this file did not)
#   * the buyer's shipping payment was ignored entirely
#
# eBay collects item + shipping and charges FVF on the TOTAL, so:
#     net = (price + buyer_ship) * (1 - FVF) - PER_ORDER - label_cost
#
# Under $20 an item ships eBay Standard Envelope; above it, Ground Advantage.
# ESE's cap is on item + shipping, which is why the threshold is 20 - 1.36.
ESE_BUYER, ESE_COST = 1.36, 0.78       # buyer pays / label costs — envelope
GA_BUYER,  GA_COST  = 4.99, 6.07       # buyer pays / label costs — Ground Advantage
ESE_MAX_ITEM = 20 - ESE_BUYER          # item + shipping must clear $20


def _ship(px):
    """(what the buyer pays, what the label costs) for an item at this price."""
    return (ESE_BUYER, ESE_COST) if px <= ESE_MAX_ITEM else (GA_BUYER, GA_COST)
MIN_SALES = 3                                   # fewer than this is not a market

GRADERS = r'(?:PSA|BGS|SGC|CGC|HGA)'
GRADE_RE = re.compile(GRADERS + r'\s*\.?\s*(10|9\.5|9|8\.5|8|7|6|5)\b', re.I)
SERIAL_RE = re.compile(r'(?<![\d/])(\d{1,3})\s*/\s*(\d{1,4})(?![\d])')
RUN_RE = re.compile(r'/\s*(\d{1,4})\b')
# 'signatures' (plural) and eBay's own '(AU, RC)' shorthand both mean autograph.
# Missing them read a Panini Throwback SIGNATURES auto as a non-auto, which would
# have comped it against unsigned base cards. AU is matched case-sensitively so
# it cannot fire on an ordinary lowercase word.
AUTO_RE = re.compile(r'\b(auto|autos|autod|autogr\w*|signature\w*|signed|sigs?)\b|\bAU\b',
                     re.I | re.X)
AUTO_RE = re.compile(r'(?i:\b(auto|autos|autogr\w*|signature\w*|signed|sigs?)\b)|(?-i:\bAU\b)')

# A damaged slab, a trimmed or altered card, or a reholder sells at a discount
# that has nothing to do with the card's value. One 'DAMAGED SLAB' Jeter sat in
# the comps at $289.99 as though it were a clean BGS 8.
DEFECT_RE = re.compile(r'\b(damaged|damage|dmg|reholder|reholdered|altered|trimmed|'
                       r'miscut|creased|crease|bent|water|stain|repack|lot\s+of|'
                       r'reprint|proxy|custom|digital|read\s+description)\b', re.I)

# A patch/relic card is a different card from a plain on-card auto of the same
# player, number and print run - categorical, exactly like auto vs non-auto. A
# Tyler Warren Rookie PATCH Auto /50 sold $131.50 against $223.50 for the on-card,
# and slipping into the comps it pulled the median down $37.
MEM_RE = re.compile(r'\b(patch|relic|relics|jersey|swatch|memorabilia|worn|'
                    r'laundry|tag|logoman|booklet)\b', re.I)

# Parallel words are matched against a VOCABULARY, never against "every leftover
# word". Matched loosely, the Valdez target ('...Refractor 1st Auto 152/499
# Prospect') demanded the words prospect AND refractor AND auto of every comp,
# and threw away five of seven real sales because sellers write the same card as
# '1st Bowman Auto /499'. Descriptors are not parallels.
PARALLEL = {
 'refractor','xfractor','x-fractor','superfractor','atomic','mojo','shimmer','wave','ray',
 'holo','foil','disco','velocity','hyper','laser','scope','mosaic','geometric',
 'galactic','interstellar','sapphire','emerald','ruby','onyx','canary','padparadscha',
 'gold','green','purple','orange','blue','red','black','pink','aqua','teal','yellow',
 'bronze','silver','white','sepia','ice','lava','magma','camo','tie-dye','speckle',
 'cracked','pulsar','vapor','reactive','logofractor','negative','independence','fuchsia',
}
# Team and city words. A team name is not an insert set and not a parallel, but
# it is in every title: 'Kansas City Royals' contributed kansas/city/royals as
# identifying words, and 'Red Sox'/'Blue Jays'/'White Sox' leak COLOURS.
TEAMS = {
 'angels','astros','athletics','braves','brewers','cardinals','cubs','diamondbacks',
 'dodgers','giants','guardians','mariners','marlins','mets','nationals','orioles',
 'padres','phillies','pirates','rangers','rays','reds','redsox','rockies','royals',
 'tigers','twins','yankees','sox','jays','bills','patriots','jets','dolphins','titans',
 'colts','texans','jaguars','chiefs','raiders','chargers','broncos','ravens','bengals',
 'browns','steelers','eagles','cowboys','commanders','packers','bears','lions','vikings',
 'saints','falcons','panthers','buccaneers','seahawks','niners','rams','cardinal',
 'lakers','celtics','warriors','knicks','nets','bulls','heat','magic','spurs','suns',
 'jazz','nuggets','clippers','pelicans','grizzlies','hornets','pacers','pistons','hawks',
 'wizards','raptors','thunder','timberwolves','mavericks','rockets','kings','bucks','seventysixers',
 'kansas','city','york','angeles','francisco','diego','antonio','orleans','england',
 'jersey','bay','vegas','carolina','dakota','arizona','atlanta','boston','chicago',
 'cleveland','dallas','denver','detroit','houston','miami','minnesota','philadelphia',
 'phoenix','pittsburgh','portland','sacramento','seattle','tampa','toronto','utah',
 'washington','baltimore','buffalo','cincinnati','indiana','memphis','milwaukee','orlando',
}

# Brand, product and sport words. Present on every card in a product, so they
# say nothing about WHICH card - they cannot identify an insert set.
GENERIC = {
 'panini','topps','upper','deck','leaf','bowman','donruss','prizm','chrome','select',
 'optic','mosaic','score','absolute','certified','contenders','immaculate','national',
 'treasures','finest','stadium','club','heritage','allen','ginter','sapphire','edition',
 'update','updates','series','one','two','draft','picks','prospects','wnba','nba','nfl',
 'mlb','nhl','football','basketball','baseball','hockey','soccer','rookie','rookies','rc',
 'card','cards','trading','sports','the','and','of','collection','insert','inserts',
 'autographs','autograph','auto','autos','signature','signatures','signed','variation',
}

# 'prizm' and 'chrome' are SET names on Panini Prizm and Topps Chrome - every card
# in those products carries the word, so treating either as a parallel rejects real
# comps wholesale. The colour beside it ('Purple Prizm') is what discriminates.
NOISE = re.compile(r'\b(rc|rookie|card|panthers|jazz|pirates|titans|giants|bills|magic|'
                   r'sports|trading|nfl|nba|mlb|opens|in|a|new|window|or|tab|the|of|and)\b', re.I)


# ---------------------------------------------------------------- card facts

# Grade descriptors. 'Gem Mint' next to 'PSA 10' is the grade written out, not a
# parallel - read as one it demanded the word 'gem' of every comp.
GRADEWORDS = {'gem','mint','mt','pristine','near','authentic','auth','qualifier',
              'graded','slab','slabbed','pop','low','high','centered'}


def player_from(title, number=None):
    """Two consecutive capitalised words that are not brand/product words.

    eBay's Player/Athlete aspect is optional and plenty of big sellers omit it;
    without a name the search queries come out blank and the surname test never
    runs, so the whole filter silently loosens."""
    t = title or ''
    # The player almost always follows the card number ('#150 Shohei Ohtani'),
    # while the words before it are the set. Searching the whole title first
    # picked 'Pitching Shohei' off '...Chrome Pitching #150 Shohei Ohtani'.
    bad = GENERIC | GRADEWORDS | TEAMS | PARALLEL
    if number:
        bad = bad | {number.lower()}
    for seg in ([t[t.find('#') + 1:], t] if '#' in t else [t]):
        words = [w for w in re.findall(r"\b[A-Z][a-zA-Z'.-]{1,14}\b", seg)
                 # a hyphenated all-caps token is a card code, never a name
                 if not re.fullmatch(r'[A-Z0-9]+-[A-Z0-9]+', w)]
        for a, b in zip(words, words[1:]):
            if not ({a.lower(), b.lower()} & bad):
                return f'{a} {b}'
    return ''


def grade_of(title):
    """'PSA 10' / 'BGS 9.5' / None. Categorical: a 9 never comps a 10."""
    m = GRADE_RE.search(title or '')
    return f'{m.group(0).split()[0].upper()} {m.group(1)}'.replace('  ', ' ') if m else None


def print_run(title):
    """The DENOMINATOR of a serial - /99 from '152/499' is wrong, 499 is right."""
    m = SERIAL_RE.search(title or '')
    if m:
        return int(m.group(2))
    m = RUN_RE.search(title or '')
    return int(m.group(1)) if m else None


def _norm_num(n):
    """'WF - 22' and '#WF-22' are the same card. eBay's Card Number aspect pads
    the hyphen; seller titles do not. Unnormalised, the aspect version matched
    none of the four sold rows and the card came back unpriceable."""
    return re.sub(r'\s*-\s*', '-', (n or '').strip().upper())


def card_number(title, hint=None):
    if hint:
        return _norm_num(hint)
    m = re.search(r'#\s*([A-Z0-9]+(?:-[A-Z0-9]+)*)', title or '', re.I)
    if m:
        return _norm_num(m.group(1))
    # Plenty of titles carry the code bare: 'First Signatures Auto FFS-TS RC'.
    # Uppercase, hyphenated, both halves short - and never a grader or a year.
    # 'ON-CARD' and friends are hyphenated ENGLISH, not card codes, and one of
    # them was read as the card number and rejected a real $231 comp.
    NOTCODE = {'ON', 'IN', 'OFF', 'NON', 'PRE', 'POST', 'MULTI', 'DUAL', 'TRI', 'LOW',
               'HIGH', 'GEM', 'NM', 'EX', 'VG', 'PSA', 'BGS', 'SGC', 'CGC', 'RC', 'SP',
               'SSP', 'MT', 'HOF', 'ALL', 'ONE', 'TWO', 'NEW', 'HOT', 'TOP', 'BOX'}
    for c in re.findall(r'\b([A-Z]{2,5}-[A-Z0-9]{1,5})\b', title or ''):
        head, tail = c.split('-', 1)
        if head not in NOTCODE and tail not in NOTCODE:
            return _norm_num(c)
    return None


# Phrases where a colour word is describing the PICTURE, not the parallel.
# '2018 Topps Chrome Ohtani #150 White Jersey' IS the base card - 'white' read as
# a parallel rejected three real $1,600-1,800 comps as different cards.
PHRASES = re.compile(r'\b(white|gray|grey|red|blue|home|away|road)\s+(jersey|uniform|'
                     r'sox|jays|hat|cap|letters|背)\b', re.I)


def parallel_words(title, number):
    """Colour/parallel words - taken from AFTER the card number only.

    Taken from the whole title, '2025 Topps Chrome BLACK ...' contributes
    'black' from the SET name and nothing can ever match."""
    # Scan the WHOLE title. Anchoring after the card number missed 'Gold
    # Refractor /50' in '...Chrome Rookie Gold Refractor /50 Tyler Warren
    # #RA-TWA', which would have comped a /50 parallel against base autos - the
    # single most expensive kind of mismatch there is.
    #
    # Safe now only because the result is intersected with the PARALLEL
    # vocabulary and the comparison is one-directional: a colour in a SET name
    # ('Topps Chrome Black') appears on both sides and cancels, and a row that
    # simply omits a colour is not rejected for it.
    t = title or ''
    t = PHRASES.sub(' ', t)
    t = GRADE_RE.sub(' ', t)
    t = re.sub(r'\bPOP\s*\d+\b', ' ', t, flags=re.I)      # 'POP 3' is a scarcity claim, not a parallel
    t = re.sub(r'\(\d+\)', ' ', t)                        # '(76)' - the seller's own lot number
    t = re.sub(r'\b[A-Z]\d{4,}\b', ' ', t)                # 'Q4705' - a cert number
    t = SERIAL_RE.sub(' ', t)
    t = RUN_RE.sub(' ', t)
    t = NOISE.sub(' ', t)
    return ({w.lower() for w in re.findall(r'[A-Za-z]{3,}', t)}
            - {'psa', 'bgs', 'sgc', 'cgc'} - GRADEWORDS)


def set_words(title, number, player, whole=False):
    """The words that name the INSERT SET - the part of a title before the card
    number, less brand/product/sport words and the player's own name.

    This is what carries identity when a seller omits the card number, which is
    most of the time: eBay ignored 'TB-CB' in search and only 1 of 60 Cameron
    Brink titles contained it. Without this, 'Courtside Action Signatures' and
    'Throwback Signatures' are indistinguishable."""
    t = (title or '')
    # Cut at the card number WHEREVER it sits, not only at a '#'. This title
    # ('...First Signatures Auto FFS-TS RC') has no '#', so the whole string was
    # scanned and 'FFS' became a required set word - rejecting every comp whose
    # seller wrote the set name without the code.
    # Truncating at the card number separates the SET name from the parallel on
    # OUR side. On a COMP's side it must not happen: '...Update #80TBA-DH 1980-81
    # REFRACTOR AUTO' would lose the word Refractor and be rejected as a different
    # card, which threw out two of nine real Harper sales.
    if not whole:
        i = t.find('#')
        if i < 0 and number:
            i = t.upper().find(number)
        if i > 0:
            t = t[:i]
    t = re.sub(r'\b(19|20)\d{2}(-\d{2})?\b', ' ', t)          # years
    names = {w.lower() for w in re.findall(r'[A-Za-z]{3,}', player or '')}
    return {w.lower() for w in re.findall(r'[A-Za-z]{3,}', t)} - GENERIC - TEAMS - names


def facts(title, number_hint=None, player_hint=None):
    n = card_number(title, number_hint)
    p = (player_hint or '').strip() or player_from(title, n)
    return {'title': title, 'number': n, 'run': print_run(title), 'grade': grade_of(title),
            'auto': bool(AUTO_RE.search(title or '')),
            'mem': bool(MEM_RE.search(title or '')),
            # Intersected with the vocabulary HERE, not only at comparison time.
            # This listing's title carries no '#', so the number could not anchor
            # the scan and the whole title came back as 'parallel' - harmless in
            # the maths, but it poisoned the fallback search query.
            'parallel': sorted(parallel_words(title, n) & PARALLEL
                               - {w.lower() for w in re.findall(r'[A-Za-z]{3,}', p)}),
            'player': p, 'set': sorted(set_words(title, n, p))}


# ---------------------------------------------------------------- filtering

def rejects(target, row):
    """Why this sold row is NOT the same card. Empty list == it is."""
    t, rt = target, row.get('t', '')
    out = []

    surname = (t['player'].split()[-1] if t['player'] else '').lower()
    if surname and surname not in rt.lower():
        out.append(f'player: no "{surname}"')

    # One-directional, like the parallel test. A seller who writes a DIFFERENT
    # card number is selling a different card; one who writes none is usually
    # selling ours - so fall back to the insert-set words instead of rejecting.
    rn = card_number(rt)
    if t['number'] and rn and rn != t['number']:
        out.append(f'number: {rn} not {t["number"]}')
    elif not (t['number'] and rn):
        # No CONFIRMED number match on both sides, so the insert-set words are the
        # only identity left and must be required. Demanding a number on our side
        # first let a non-Refractor $435 sale into a Refractor comp whenever the
        # listing title carried no card code - which is most titles.
        missing = set(t['set']) - set_words(rt, rn, t['player'], whole=True)
        if missing:
            out.append('set: no ' + ','.join(sorted(missing)))

    g = grade_of(rt)
    if (t['grade'] or None) != (g or None):
        out.append(f'grade: {g or "raw"} vs {t["grade"] or "raw"}')

    r = print_run(rt)
    if (t['run'] or None) != (r or None):
        out.append(f'print run: /{r} vs /{t["run"]}' if r or t['run'] else '')
        out = [x for x in out if x]

    if bool(AUTO_RE.search(rt)) != t['auto']:
        out.append('auto vs non-auto')

    if bool(MEM_RE.search(rt)) != t['mem']:
        out.append('patch/relic vs plain card')

    if DEFECT_RE.search(rt) and not DEFECT_RE.search(t['title'] or ''):
        out.append('damaged/altered - not a clean comp')

    # One-directional on purpose. A seller OMITTING 'Refractor' is describing the
    # same card; a seller ADDING 'Purple' is describing a different one. Absence
    # is not contradiction, so only extras on their side are disqualifying.
    tp = set(t['parallel']) & PARALLEL
    rp = parallel_words(rt, t['number']) & PARALLEL
    if rp - tp:
        out.append('parallel: ' + ','.join(sorted(rp - tp)) + ' is a different card')
    return out


# ---------------------------------------------------------------- economics

def max_bid(comp):
    if comp >= 100:  return 0.7175 * comp - 5.30
    if comp >= 20:   return 0.6675 * comp - 5.30
    return 0.4675 * comp - 1.18


def net_of(px):
    """What reaches Craig after eBay, with the buyer paying shipping."""
    buyer, cost = _ship(px)
    return (px + buyer) * (1 - FVF) - PER_ORDER - cost


def break_even_of(cost):
    """Lowest list price whose net covers `cost`. Solved by walking the price
    rather than inverting, because the ESE/Ground-Advantage switch at $18.64
    makes net_of a step function - a closed form silently picks the wrong band."""
    px = 0.01
    while px < 100000:
        if net_of(px) >= cost:
            return round(px + 0.004, 2)
        px += 0.01
    return float('inf')


def verdict(cost, comp, n):
    cap, be, net = max_bid(comp), break_even_of(cost), net_of(comp)
    profit = net - cost
    lines = [f'  comp (median of {n} sales)   ${comp:,.2f}',
             f'  max-bid cap                ${cap:,.2f}   ' +
             (f'-> OVER by ${cost - cap:,.2f}' if cost > cap else f'-> inside by ${cap - cost:,.2f}'),
             f'  break-even resale          ${be:,.2f}',
             f'  sell at comp               net ${net:,.2f}   profit ${profit:+,.2f}']
    if n < MIN_SALES:
        call = f'NO VERDICT - only {n} matching sale(s). Not a market.'
    elif cost <= cap and profit > 0:
        call = f'BUY - inside the cap, makes ${profit:,.2f} at comp.'
    elif profit > 0:
        call = f'THIN - over the cap but still ${profit:,.2f} at comp. Offer ${cap:,.2f}.'
    else:
        call = f'PASS - loses ${-profit:,.2f} at its own comp. Offer no more than ${cap:,.2f}.'
    return lines, call


# ---------------------------------------------------------------- eBay lookup

def item_id(s):
    s = s.strip()
    if re.fullmatch(r'\d{9,15}', s):
        return s
    if 'ebay.io' in s or '/m/' in s:
        s = subprocess.run(['curl', '-s', '-o', '/dev/null', '-w', '%{redirect_url}', '-A', 'curl/8.0', s],
                           capture_output=True, text=True).stdout.strip() or s
    m = re.search(r'/itm/(?:.*?/)?(\d{9,15})', s)
    return m.group(1) if m else None


def browse(iid):
    """Item facts from the Browse API, cached on disk.

    Re-running a card should not cost an API call: hammering it during a testing
    pass earned an HTTP 429 and every regression then failed for a reason that
    had nothing to do with the code."""
    cache = os.path.join(HERE, '.item-cache')
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, f'{iid}.json')
    if os.path.exists(path):
        return json.load(open(path))
    sys.path.insert(0, HERE)
    import base64, urllib.error, urllib.request
    a = open(os.path.expanduser('~/.dtp-ebay-appid')).read().strip()
    c = open(os.path.expanduser('~/.dtp-ebay-cert')).read().strip()
    b = base64.b64encode(f'{a}:{c}'.encode()).decode()
    body = urllib.parse.urlencode({'grant_type': 'client_credentials',
                                   'scope': 'https://api.ebay.com/oauth/api_scope'}).encode()
    tok = json.load(urllib.request.urlopen(urllib.request.Request(
        'https://api.ebay.com/identity/v1/oauth2/token', data=body,
        headers={'Authorization': 'Basic ' + b,
                 'Content-Type': 'application/x-www-form-urlencoded'}), timeout=30))['access_token']
    u = 'https://api.ebay.com/buy/browse/v1/item/' + urllib.parse.quote(f'v1|{iid}|0')
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(
            u, headers={'Authorization': 'Bearer ' + tok,
                        'X-EBAY-C-MARKETPLACE-ID': 'EBAY_US'}), timeout=30))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            sys.exit('eBay Browse API rate limit (429). Wait a few minutes, or pass '
                     '--title "<listing title>" --price N to run without it.')
        if e.code == 404:
            sys.exit(f'eBay has no item {iid} - the listing has probably ended.')
        raise
    json.dump(d, open(path, 'w'))
    return d


def snippet(t):
    """The JS to paste, with THIS card's facts baked in.

    A full sold page is ~7KB of JSON and the console round-trip truncates near
    900 bytes, so the page does a COARSE pre-filter - surname, card number and
    grade token only - and ships back the handful that survive. Those three
    tests can only remove cards that are obviously not ours. Every judgement
    that has ever gone wrong (print run, parallel, auto) stays in Python below,
    where it is testable and where --show-rejects can explain itself."""
    surname = (t['player'].split()[-1] if t['player'] else '').lower()
    g = t['grade'] or ''
    return ("[...document.querySelectorAll('li.s-item, li.s-card')].map(li=>{"
            "const t=(li.querySelector('.s-item__title, .s-card__title')?.innerText||'')"
            ".replace(/\\n.*/s,'').replace(/^NEW LISTING/,'').trim();const a=li.innerText;"
            "return {t,p:parseFloat(((li.querySelector('.s-item__price, .s-card__price')?.innerText)||'')"
            ".replace(/[^0-9.]/g,'')),d:(a.match(/Sold\\s+(\\w{3}\\s+\\d{1,2},\\s+\\d{4})/)||[])[1],"
            "b:(a.match(/(\\d+)\\s+bids?/)||[])[1]||'BIN',"
            "obo:/Best Offer|offer accepted/i.test(a)};})"
            ".filter(r=>r.t&&r.d&&r.t!=='Shop on eBay')"
            f".filter(r=>/{surname}/i.test(r.t))"
            + (f".filter(r=>/{t['number']}/i.test(r.t)||!/#\\s*[A-Z]{{1,4}}-?[A-Z0-9]+/i.test(r.t))"
               if t['number'] else '')
            + ''.join(f".filter(r=>/{w}/i.test(r.t))" for w in t['set'][:2])
            + (f".filter(r=>/{g.replace(' ', chr(92)+'s*')}/i.test(r.t))" if g
               else ".filter(r=>!/(PSA|BGS|SGC|CGC)\\s*\\d/i.test(r.t))"))


EXTRACTOR = r'''[...document.querySelectorAll('li.s-item, li.s-card')].map(li=>{
 const t=(li.querySelector('.s-item__title, .s-card__title')?.innerText||'').replace(/\n.*/s,'').replace(/^NEW LISTING/,'').trim();
 const a=li.innerText;
 return {t,p:parseFloat(((li.querySelector('.s-item__price, .s-card__price')?.innerText)||'').replace(/[^0-9.]/g,'')),
 d:(a.match(/Sold\s+(\w{3}\s+\d{1,2},\s+\d{4})/)||[])[1],b:(a.match(/(\d+)\s+bids?/)||[])[1]||'BIN'};
}).filter(r=>r.t&&r.d&&r.t!=='Shop on eBay')'''


def receive(port=8731, timeout=180):
    """Take the sold rows straight from the browser instead of via copy-paste.

    The clipboard is not available to injected script (execCommand('copy')
    returns false without a user gesture), and 60 rows of JSON is too much to
    hand-carry. So comp.py listens on localhost and the page POSTs to it.
    Content-Type stays text/plain so the request is CORS-simple and never
    triggers an OPTIONS preflight."""
    got = {}
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got['rows'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers(); self.wfile.write(b'ok')
            threading.Thread(target=self.server.shutdown).start()
        def log_message(self, *a): pass
    with socketserver.TCPServer(('127.0.0.1', port), H) as srv:
        srv.timeout = timeout
        print(f'  listening on 127.0.0.1:{port} ... run the snippet in the browser')
        srv.serve_forever()
    return got.get('rows', [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('item')
    ap.add_argument('--sold', help='JSON file of sold rows captured from the browser')
    ap.add_argument('--price', type=float, help='override the all-in cost')
    ap.add_argument('--show-rejects', action='store_true')
    ap.add_argument('--expect', help='sha256 of the JSON as the PAGE produced it; the run '
                                     'aborts unless the local file hashes the same')
    ap.add_argument('--listen', action='store_true', help='wait for the browser to POST the sold rows')
    ap.add_argument('--port', type=int, default=8731)
    ap.add_argument('--no-log', action='store_true',
                    help='skip comp-log.csv - used by the self-test, which would '
                         'otherwise fill the decision log with replays of old cards')
    ap.add_argument('--title', help='listing title, to work without the Browse API '
                                    '(rate limit, or an ended listing)')
    args = ap.parse_args()

    iid = item_id(args.item)
    if not iid:
        sys.exit('could not find an item id in that argument')
    if args.title:
        # --price and --title together make the tool usable when Browse is rate
        # limited or the listing has ended. Everything downstream reads the title,
        # so nothing about the filtering changes.
        d = {'title': args.title, 'price': {'value': args.price or 0},
             'seller': {}, 'buyingOptions': [], 'localizedAspects': []}
    else:
        d = browse(iid)
    asp = {a['name']: a['value'] for a in d.get('localizedAspects', [])}
    ship = 0.0
    if not args.title and d.get('shippingOptions'):
        ship = float(d['shippingOptions'][0].get('shippingCost', {}).get('value') or 0)
    cost = args.price if args.price is not None else float(d['price']['value']) + ship
    t = facts(d['title'], asp.get('Card Number'), asp.get('Player/Athlete'))
    s = d.get('seller', {})

    print(f"\nLISTING  {d['title']}")
    print(f"  ${float(d['price']['value']):,.2f} + ${ship:,.2f} ship = ${cost:,.2f} all-in"
          f"   [{', '.join(d.get('buyingOptions') or [])}]")
    print(f"  seller {s.get('username')} {s.get('feedbackPercentage')}% over {s.get('feedbackScore')}"
          f"   returns={d.get('returnTerms',{}).get('returnsAccepted')}"
          f"   images={1+len(d.get('additionalImages') or [])}")
    print(f"  READ AS  number={t['number']}  grade={t['grade'] or 'raw'}  run={t['run'] and '/'+str(t['run'])}"
          f"  auto={t['auto']}  mem={t['mem']}  parallel={t['parallel']}")

    # Several searches, best first. eBay silently IGNORES an unmatched card
    # number and hands back the player's whole catalogue, so a number-only query
    # can look like a clean search and be nothing of the kind. Always check how
    # many returned rows actually contain the number before trusting it.
    who = asp.get('Player/Athlete') or t['player']
    cands = []
    if t['number']:
        cands.append(f"{who} {t['number']}")
    if t['set']:
        cands.append(' '.join([who] + t['set'] + (['auto'] if t['auto'] else [])))
    if t['parallel']:
        cands.append(' '.join([who] + t['set'][:2] + t['parallel']))
    if not cands:
        cands = [who]
    urls = ['https://www.ebay.com/sch/i.html?_nkw=' + urllib.parse.quote(q) +
            '&_sacat=0&LH_Sold=1&LH_Complete=1&_ipg=60' for q in cands]
    url = urls[0]

    if args.listen:
        rows = receive(args.port)
        json.dump(rows, open(os.path.join(HERE, 'sold-last.json'), 'w'))
        args.sold = os.path.join(HERE, 'sold-last.json')

    if not args.sold:
        print(f"\n*** NO VERDICT WITHOUT SOLD DATA ***")
        print(f"  1. open one of these (first that returns real matches):")
        for q, u in zip(cands, urls):
            print(f"       [{q}]\n       {u}")
        print(f"  2. paste this into the console on that page:\n")
        print('await (async r=>({sha:[...new Uint8Array(await crypto.subtle.digest('
              '"SHA-256",new TextEncoder().encode(JSON.stringify(r.map(x=>Object.fromEntries('
              'Object.entries(x).sort()))))))].map(b=>b.toString(16).padStart(2,"0"))'
              '.join("").slice(0,16),n:r.length,rows:r}))(' + snippet(t) + ')\n')
        print(f"  3. rerun  python3 reports/comp.py {iid} --sold sold.json")
        print(f"\n  or one-shot:  python3 reports/comp.py {iid} --listen")
        print(f"  then in the console on that page:")
        print(f"    fetch('http://127.0.0.1:8731',{{method:'POST',body:JSON.stringify(ROWS)}})")
        print(f"    where ROWS = the array from reports/sold-extract.js\n")
        return

    blob = open(args.sold, 'rb').read()
    # Integrity check. The rows reach this file by being read out of a browser
    # console and retyped, and a transcription step that nothing verifies is a
    # place for judgement to re-enter the evidence - which is the whole failure
    # this tool exists to prevent. The page prints a sha256 of what it actually
    # saw; --expect refuses to run on anything else.
    if args.expect:
        import hashlib
        # ensure_ascii=False is REQUIRED, not cosmetic. Python defaults to True
        # and escapes non-ASCII as \uXXXX; JSON.stringify in the browser emits
        # the raw character. So any title carrying an emoji or a smart
        # apostrophe -- a fire emoji and Struttin' on the Carnell Tate S-17,
        # 2026-09-21 -- hashed differently on the two sides and raised a
        # TRANSCRIPTION MISMATCH on rows that were captured perfectly. The guard
        # was crying wolf on exactly the listings eBay sellers title most
        # aggressively.
        got = hashlib.sha256(json.dumps(json.loads(blob), separators=(',', ':'),
                                        sort_keys=True,
                                        ensure_ascii=False).encode('utf-8')).hexdigest()
        if not got.startswith(args.expect.strip().lower()[:16]):
            sys.exit(f'TRANSCRIPTION MISMATCH\n  page said {args.expect[:16]}\n'
                     f'  file is   {got[:16]}\nRe-capture the rows; do not proceed.')
        print(f'  sold rows verified against the page  ({got[:16]})')
    rows = json.loads(blob)
    rows = rows if isinstance(rows, list) else rows.get('rows', [])
    kept, tossed = [], []
    for r in rows:
        why = rejects(t, r)
        (tossed if why else kept).append((r, why))

    print(f"\nSOLD SEARCH  {len(rows)} rows -> {len(kept)} are this exact card")
    for r, _ in sorted(kept, key=lambda x: x[0].get('d') or ''):
        print(f"   {(r.get('d') or '').ljust(14)} ${r['p']:>9,.2f}  {str(r.get('b','')).rjust(3)}  {r['t'][:66]}")
    if args.show_rejects:
        print('\n  rejected:')
        for r, why in tossed[:25]:
            print(f"   ${r['p']:>9,.2f}  {r['t'][:52]:<52} | {'; '.join(why)}")

    if not kept:
        print('\n*** NO SALES OF THIS EXACT CARD. Cannot price it. Do not buy on interpolation. ***\n')
        return
    ps = sorted(r['p'] for r, _ in kept)
    comp = statistics.median(ps)
    print(f"\n  range ${ps[0]:,.2f}-${ps[-1]:,.2f}   median ${comp:,.2f}")

    # BEST OFFER ROWS ARE NOT SALE PRICES. Verified 2026-09-15 against the eBay
    # app's own Price-insights panel: a Jaxson Dart PSA 9 that the app reports as
    # "$1,350, Offer accepted" on Sep 14 appears in the sold SEARCH at $2,399.99.
    # The search prints what the seller ASKED, not what the buyer paid - 78% high
    # on that one row. Any row carrying the Best Offer badge is an upper bound of
    # unknown slack, so it cannot sit in a median.
    obo = [r for r, _ in kept if r.get('obo') and not str(r.get('b', 'BIN')).isdigit()]
    if obo:
        print(f"  dropped {len(obo)} Best-Offer listing(s) - eBay shows the ASK on those, "
              f"not the accepted price (measured 78% high on a verified case)")
        kept = [(r, w) for r, w in kept if not (r.get('obo')
                                                and not str(r.get('b', 'BIN')).isdigit())]
        if not kept:
            print('\n*** every matching row was a Best Offer listing. No usable prices. ***\n')
            return
        ps = sorted(r['p'] for r, _ in kept)
        print(f"  remaining {len(ps)}: range ${ps[0]:,.2f}-${ps[-1]:,.2f}  "
              f"median ${statistics.median(ps):,.2f}")

    # An AUCTION close is many buyers competing; a BIN is one seller's asking
    # price that happened to be taken. On the Brett /25 the listing's own $199.99
    # ask was the single BIN in the set and every auction landed $93-110.
    auc = [(r, p) for r, p in ((r, r['p']) for r, _ in kept) if str(r.get('b', 'BIN')).isdigit()]
    bins = [(r, p) for r, p in ((r, r['p']) for r, _ in kept) if not str(r.get('b', 'BIN')).isdigit()]
    basis = [(r, p) for r, _ in kept for p in [r['p']]]
    if len(auc) >= MIN_SALES and bins:
        ma, mb = statistics.median([p for _, p in auc]), statistics.median([p for _, p in bins])
        print(f"  auctions ({len(auc)}) median ${ma:,.2f}   |   BIN ({len(bins)}) median ${mb:,.2f}")
        if mb > ma * 1.15:
            print(f"  ^ BINs sit {mb / ma - 1:+.0%} over the auctions. Using the AUCTIONS - "
                  f"they are the price buyers COMPETE to.")
            basis = auc
    comp = statistics.median([p for _, p in basis])

    # Recency, applied to that same basis and only with a real sample. Run on four
    # sales it let one outlying BIN pull a $103 card's comp up to $155, and it
    # silently undid the auction preference above.
    def when(r):
        try:
            return __import__('datetime').datetime.strptime(r['d'].replace(',', ''), '%b %d %Y')
        except Exception:
            return None
    dated = sorted([(w, p) for r, p in basis for w in [when(r)] if w])
    if len(dated) >= 6:
        half = len(dated) // 2
        mo = statistics.median([p for _, p in dated[:half]])
        mr = statistics.median([p for _, p in dated[half:]])
        if abs(mr - mo) > 0.12 * mo:
            print(f"  {'FALLING' if mr < mo else 'RISING'}: older half ${mo:,.2f} -> "
                  f"newer ${mr:,.2f} ({mr / mo - 1:+.0%}). Pricing against ${mr:,.2f}.")
            comp = mr

    # Wide dispersion means the "median" is describing several markets at once.
    if len(ps) >= MIN_SALES and ps[-1] > 1.6 * ps[0]:
        print(f"  ! spread is {ps[-1] / ps[0]:.1f}x (${ps[0]:,.2f}-${ps[-1]:,.2f}). Treat the "
              f"comp as soft - check the rejects for a parallel that slipped through.")
    lines, call = verdict(cost, comp, len(ps))
    print(f"\nYOUR COST  ${cost:,.2f}")
    print('\n'.join(lines))
    print(f"\n  >>> {call}\n")

    # Every verdict is appended, so in three months it can be checked against what
    # actually happened. A comp process that is never scored is just a habit.
    if args.no_log:
        return
    import csv, datetime
    log = os.path.join(HERE, 'comp-log.csv')
    new = not os.path.exists(log)
    with open(log, 'a', newline='') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(['when', 'item', 'title', 'cost', 'comp', 'n_sales',
                        'cap', 'break_even', 'profit_at_comp', 'call'])
        w.writerow([datetime.date.today().isoformat(), iid, d['title'][:90],
                    f'{cost:.2f}', f'{comp:.2f}', len(ps), f'{max_bid(comp):.2f}',
                    f'{break_even_of(cost):.2f}',
                    f'{net_of(comp) - cost:.2f}', call.split(" -")[0]])
    print(f"  logged to reports/comp-log.csv\n")


if __name__ == '__main__':
    main()
