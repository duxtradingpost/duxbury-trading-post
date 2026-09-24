#!/usr/bin/env python3
"""Audit live eBay listings for the faults that cost sales quietly.

    python3 reports/ebay-audit.py          # write ebay-audit.json for the briefing
    python3 reports/ebay-audit.py --print  # and show it

Runs headless on client credentials, so unlike Terapeak this needs no browser and
no human — it belongs in the 07:00 job.

Why it exists: the Josh Allen Glass Mosaic sat at $150 with a print line and back
damage, an EMPTY condition-notes field, and a description of pure marketing fluff
("highly coveted... must-have... rare"). Three separate buyers had to message and
ask what was wrong with it; one then offered $130 and walked. That is not a
pricing problem, it is an undisclosed-flaw problem, and nothing in the system
would ever have surfaced it.

Checks, in order of what they cost:
  nothing about condition  a raw card whose listing says nothing, anywhere, about
                      its condition invites the "what's wrong with it" message,
                      or a return. Graded cards are exempt: the grade IS the
                      disclosure.
  thin photos         under PHOTO_MIN, buyers cannot self-serve on condition
  fluff description   marketing adjectives and no condition language at all

There is deliberately no "blank condition notes" check — eBay's trading card
category has no free-text condition field at all, so that fault could never be
cleared by any action and nagged about 76 listings daily. See audit_item().
"""
import base64, json, os, re, sys, urllib.error, urllib.parse, urllib.request
from datetime import date

HERE   = os.path.dirname(os.path.abspath(__file__))
OUT    = os.path.join(HERE, 'ebay-audit.json')
APPID  = os.path.expanduser('~/.dtp-ebay-appid')
CERT   = os.path.expanduser('~/.dtp-ebay-cert')
PHOTO_MIN = 4
FLUFF = ('highly coveted', 'must-have', 'must have', 'stunning', 'don\'t miss out',
         'rare and high', 'perfect addition', 'a must for any')
CONDITION_WORDS = ('corner', 'edge', 'surface', 'centering', 'print line', 'crease',
                   'scratch', 'scrape', 'ding', 'whitening', 'gloss', 'off-center',
                   'near mint', 'condition', 'flaw', 'damage', 'sleeve')


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


def strip_html(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s or '')).strip()


_COND_RE = re.compile(r'\b(?:' + '|'.join(
    w.replace(' ', r'\s+').replace('-', r'[- ]') for w in CONDITION_WORDS) + r')\b')


def says_anything_about_condition(blob):
    """Does this text mention condition at all — as WORDS, not as substrings?

    The naive `any(w in blob ...)` this replaces matched 'ding' inside
    "outstanding", "including" and "leading", which appear in almost every
    auto-generated marketing description. Seventeen raw cards — among them the
    $390 Achane, the $213 Tolle and the $210 Garrett — passed the condition
    check on the strength of the word "outstanding" while disclosing nothing.
    That is the exact failure the Glass Mosaic taught us to look for, hidden by
    a substring match."""
    return bool(_COND_RE.search(blob))


def audit_item(d):
    """Everything wrong with one listing, cheapest fault first."""
    faults = []
    cond_notes = (d.get('conditionDescription') or '').strip()
    desc = strip_html(d.get('description') or d.get('shortDescription') or '')
    blob = (cond_notes + ' ' + desc).lower()
    graded = bool(re.search(r'\b(psa|bgs|sgc|cgc)\s*\d', (d.get('title') or ''), re.I))

    # There is NO separate "condition notes" fault, on purpose. eBay's trading
    # card category has no free-text condition field — `conditionDescription`
    # cannot be set there by the listing form or the API — so reporting its
    # absence flagged 76 listings with a fault that no action could ever clear,
    # every morning, forever. The condition note goes in the description
    # instead, and the only question worth asking is whether a buyer can find
    # condition information anywhere at all.
    if not graded and not says_anything_about_condition(blob):
        faults.append('nothing about condition anywhere')
    photos = len(d.get('additionalImages') or []) + (1 if d.get('image') else 0)
    if photos < PHOTO_MIN:
        faults.append(f'only {photos} photo(s)')
    if any(f in desc.lower() for f in FLUFF):
        faults.append('boilerplate description')
    return faults, photos


def already_ran_today():
    """Has today's audit already been done?

    The briefing job polls every 30 minutes so it can survive sleep, and these
    eBay calls used to ride along on every single tick: 93 Browse lookups x 48
    ticks was ~4,500 calls a day from this script alone, and ebay-market.py spent
    roughly as many again. The Browse API allows 5,000 a day total, so the quota
    was gone by mid-morning and every later run came back 429 — which this script
    counted as "errors" and then reported as ZERO FAULTS, a clean bill of health
    for 93 listings it had not actually looked at. Once a day is all the audit
    needs; the polling is there for sleep, not for freshness."""
    try:
        return json.load(open(OUT)).get('ran') == str(date.today())
    except Exception:
        return False


def main():
    if '--once-daily' in sys.argv and already_ran_today():
        return 0
    tok = token()
    # Listings come from the export; the API is used to read each one back.
    import csv, glob
    exp = max(glob.glob(os.path.join(HERE, 'products_export*.csv')), key=os.path.getmtime)
    skus = {}
    for r in csv.DictReader(open(exp)):
        if r.get('Status') == 'active' and (r.get('Variant Barcode') or '').strip():
            skus[r['Variant Barcode'].strip().lstrip("'")] = r['Title']

    ids = []
    try:
        ids = json.load(open(os.path.join(HERE, 'ebay-itemids.json')))
    except Exception:
        pass
    if not ids:
        print('no ebay-itemids.json — populate it with {sku: itemId} to audit listings',
              file=sys.stderr)
        json.dump({'checked': 0, 'faults': [], 'note': 'no item ids available'}, open(OUT, 'w'))
        return 0

    rows, errors = [], 0
    for sku, iid in ids.items():
        try:
            d = get(f'https://api.ebay.com/buy/browse/v1/item/v1|{iid}|0', tok)
        except urllib.error.HTTPError:
            errors += 1
            continue
        faults, photos = audit_item(d)
        if faults:
            rows.append({'sku': sku, 'itemId': iid, 'title': d.get('title', '')[:70],
                         'price': float(d['price']['value']), 'photos': photos,
                         'faults': faults})
    rows.sort(key=lambda r: (-len(r['faults']), -r['price']))
    # If every lookup failed there is no audit, only an empty list that LOOKS
    # like a pass. Say so, and leave the last real result on disk rather than
    # overwriting it with nothing.
    if ids and errors == len(ids):
        print(f'ebay-audit: ALL {errors} lookups failed (rate limit or token) — '
              f'{os.path.basename(OUT)} left unchanged, NOT a clean audit', file=sys.stderr)
        return 1
    json.dump({'checked': len(ids), 'errors': errors, 'faults': rows,
               'ran': str(date.today())}, open(OUT, 'w'), indent=1)
    warn = f', {errors} FAILED to load' if errors else ''
    print(f'{len(ids)} listings checked, {len(rows)} with faults{warn} -> {os.path.basename(OUT)}')
    if '--print' in sys.argv:
        for r in rows[:15]:
            print(f"  ${r['price']:>8.2f}  {', '.join(r['faults']):<52} {r['title'][:42]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
