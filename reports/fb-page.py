#!/usr/bin/env python3
"""A click-to-copy page for this week's Facebook Marketplace listings.

    python3 reports/fb-page.py    ->  ig-cards/MARKETPLACE.html

Marketplace posting cannot be automated: Meta exposes no listing API for general
items, and scripting their form violates the terms on automated behaviour — a
restricted account would cost the Facebook page, Instagram selling and the card
groups, which are the fee-free channels this whole exercise is trying to build.

So this reduces the manual work instead of pretending to remove it. One button
per field, the photo shown next to it, and the fields in the order Meta's form
asks for them. Open it, keep it beside the Marketplace tab, work down the list.
"""
import html, json, os, re, sys

HERE  = os.path.dirname(os.path.abspath(__file__))
CARDS = os.path.join(HERE, 'ig-cards')
RAW   = os.path.join(CARDS, '_raw')
WEEK  = os.path.join(HERE, 'ig-this-week.json')
OUT   = os.path.join(CARDS, 'MARKETPLACE.html')
CATEGORY = 'Toys &amp; Games &gt; Collectible Trading Cards'


def condition(t):
    return 'New' if re.search(r'\b(psa|bgs|sgc|cgc)\s*\d', t, re.I) else 'Used - Like New'


def describe(t):
    bits = [t.rstrip('.') + '.']
    g = re.search(r'\b(PSA|BGS|SGC|CGC)\s*(\d+(?:\.\d)?)\b', t, re.I)
    if g:
        bits.append(f'Graded {g.group(1).upper()} {g.group(2)}.')
    run = re.search(r'/(\d+)\b', t)
    if run:
        bits.append(f'Serial numbered to {run.group(1)} — short print.')
    bits += ['Stored in a sleeve and top-loader, shipped in a bubble mailer with '
             'tracking, or free local pickup in Duxbury.',
             'Duxbury Trading Post — more cards available, ask for the list.']
    return ' '.join(bits)


def main():
    wk = json.load(open(WEEK))
    picks = wk.get('picks') or []
    raws = sorted(os.listdir(RAW)) if os.path.isdir(RAW) else []
    cards = []
    for i, p in enumerate(picks, 1):
        slug = re.sub(r'[^A-Za-z0-9]+', '-', p['title'])[:56].strip('-')
        photo = next((f for f in raws if slug[:28] in f), '')
        cards.append(f'''<section>
  <div class=ph>{f'<img src="_raw/{html.escape(photo)}" alt="">' if photo else '<div class=no>no photo</div>'}</div>
  <div class=fields>
    <div class=n>{i:02d} <span class=meta>eBay ${p['ebay']:.0f} · comp ${p['comp_lo']:.0f}-{p['comp_hi']:.0f} · P/L {p['profit']:+.2f} · pickup adds $6.07</span></div>
    <button data-c="{html.escape(p['title'], quote=True)}"><b>Title</b><span>{html.escape(p['title'])}</span></button>
    <button data-c="{p['post_at']:.0f}"><b>Price</b><span>${p['post_at']:.0f}</span></button>
    <button data-c="Toys &amp; Games"><b>Category</b><span>{CATEGORY}</span></button>
    <button data-c="{condition(p['title'])}"><b>Condition</b><span>{condition(p['title'])}</span></button>
    <button data-c="{html.escape(describe(p['title']), quote=True)}"><b>Description</b><span>{html.escape(describe(p['title']))}</span></button>
  </div>
</section>''')
    doc = f'''<!doctype html><meta charset=utf-8><title>Marketplace — this week</title>
<style>
:root{{--g:#0A2814;--c:#F7F4EB;--s:#B9CDC0}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--g);color:var(--c);font:15px/1.5 -apple-system,system-ui,sans-serif}}
header{{padding:22px 26px;border-bottom:1px solid #1c4429}}
h1{{margin:0;font-size:19px}} header p{{margin:6px 0 0;color:var(--s);font-size:13px;max-width:70ch}}
section{{display:flex;gap:18px;padding:18px 26px;border-bottom:1px solid #16351f;align-items:flex-start}}
.ph img{{width:120px;border-radius:8px;display:block}}
.no{{width:120px;height:165px;background:#16351f;border-radius:8px}}
.fields{{flex:1;min-width:0}}
.n{{font-weight:600;margin-bottom:8px}}
.meta{{font-weight:400;color:var(--s);font-size:12px}}
button{{display:block;width:100%;text-align:left;margin:0 0 6px;padding:8px 11px;border:1px solid #1c4429;
background:#0d3319;color:var(--c);border-radius:7px;cursor:pointer;font:inherit}}
button:hover{{background:#164a26;border-color:#2c6b3f}}
button b{{display:inline-block;width:92px;color:var(--s);font-size:12px;text-transform:uppercase;letter-spacing:.04em;vertical-align:top}}
button span{{display:inline-block;width:calc(100% - 100px);white-space:pre-wrap;word-break:break-word}}
button.ok{{background:#1d6b39;border-color:#2f8f52}}
</style>
<header><h1>Facebook Marketplace — {len(picks)} listings</h1>
<p>Click a field to copy it, then paste into Marketplace &rsaquo; Create new listing &rsaquo; Item for sale.
Photos are in <code>_raw</code>. Local pickup is fee-free, so every P/L below is conservative by the $6.07 postage.</p></header>
{''.join(cards)}
<script>
document.addEventListener('click',e=>{{
  const b=e.target.closest('button'); if(!b) return;
  navigator.clipboard.writeText(b.dataset.c).then(()=>{{
    b.classList.add('ok'); setTimeout(()=>b.classList.remove('ok'),700);
  }});
}});
</script>'''
    open(OUT, 'w').write(doc)
    print(f'{len(picks)} listings -> {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
