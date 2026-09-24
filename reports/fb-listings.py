#!/usr/bin/env python3
"""Paste-ready Facebook Marketplace listings for this week's rotation.

    python3 reports/fb-listings.py

Marketplace has no API — every listing is typed by hand into Meta's form. So the
job here is not to automate the posting, which is impossible, but to remove the
typing: one block per card with the title, price, category, condition and
description already written, next to the photo to upload.

Local pickup on Marketplace carries NO fee at all — no 13.25% like eBay, no ~5%
like Meta checkout. For a local buyer it is the highest-net channel Craig has,
which is why the same cards are worth listing here as well as on Instagram.

Prices come from the same verified-comp median as the Instagram frames, so the
two channels cannot drift apart.
"""
import json, os, re, shutil, sys

HERE  = os.path.dirname(os.path.abspath(__file__))
CARDS = os.path.join(HERE, 'ig-cards')
RAW   = os.path.join(CARDS, '_raw')
WEEK  = os.path.join(HERE, 'ig-this-week.json')
OUT   = os.path.join(CARDS, 'MARKETPLACE-listings.txt')

# Marketplace's own taxonomy. Cards sit under Toys & Games rather than Sporting
# Goods — listing them as sporting goods is a common way to get no views.
CATEGORY = 'Toys & Games  >  Collectible Trading Cards'


def condition(title):
    """Marketplace's condition picker has no 'graded' option, so a graded card is
    New and the grade goes in the description where buyers actually read it."""
    if re.search(r'\b(psa|bgs|sgc|cgc)\s*\d', title, re.I):
        return 'New'
    return 'Used - Like New'


def describe(p):
    t = p['title']
    bits = []
    bits.append(t.rstrip('.') + '.')
    g = re.search(r'\b(PSA|BGS|SGC|CGC)\s*(\d+(?:\.\d)?)\b', t, re.I)
    if g:
        bits.append(f"Graded {g.group(1).upper()} {g.group(2)}.")
    run = re.search(r'/(\d+)\b', t)
    if run:
        bits.append(f"Serial numbered to {run.group(1)} — short print.")
    bits.append('Stored in a sleeve and top-loader, shipped in a bubble mailer '
                'with tracking, or free local pickup in Duxbury.')
    bits.append('Duxbury Trading Post — more cards available, ask for the list.')
    return ' '.join(bits)


def main():
    try:
        wk = json.load(open(WEEK))
    except Exception:
        sys.exit('no ig-this-week.json — run ig-wednesday.py first')
    picks = wk.get('picks') or []
    if not picks:
        sys.exit('nothing staged this week')

    lines = [
        'FACEBOOK MARKETPLACE — this week\'s listings',
        '=' * 62,
        'Marketplace has no bulk upload; each of these is typed once into',
        'Marketplace > Create new listing > Item for sale. Photos are in the',
        '_raw folder beside this file (use those, not the story frames — the',
        'price is a form field here, so a price burned into the image is noise).',
        '',
        'Local pickup is fee-free. Shipping through Meta checkout is not.',
        '', '']
    for i, p in enumerate(picks, 1):
        slug = re.sub(r'[^A-Za-z0-9]+', '-', p['title'])[:56].strip('-')
        photo = next((f for f in sorted(os.listdir(RAW))
                      if slug[:30] in f), '(photo not staged)') if os.path.isdir(RAW) else '?'
        lines += [
            f'--- {i:02d} ' + '-' * 56,
            f"TITLE     {p['title'][:100]}",
            f"PRICE     ${p['post_at']:.0f}",
            f'CATEGORY  {CATEGORY}',
            f"CONDITION {condition(p['title'])}",
            'DESCRIPTION',
            '  ' + describe(p),
            f"PHOTO     _raw/{photo}",
            f"  (eBay ask ${p['ebay']:.2f} · comp ${p['comp_lo']:.0f}-{p['comp_hi']:.0f}"
            f" · your P/L at this price {p['profit']:+.2f})",
            '']
    open(OUT, 'w').write('\n'.join(lines))
    print(f'{len(picks)} listings -> {OUT}')
    print(f'photos already in {RAW}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
