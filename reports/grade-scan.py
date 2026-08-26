#!/usr/bin/env python3
"""
Duxbury Trading Post — raw-to-graded buy scanner.

Answers one question: of everything listed on eBay right now, which raw cards
are worth buying to send to PSA?

    python3 grade-scan.py --check      what data access do I actually have
    python3 grade-scan.py --dry        run without emailing
    python3 grade-scan.py              run and email the results
    python3 grade-scan.py --gem "2020 panini prizm silver" 355 906 172 50
                                       record a gem rate read off GemRate
    python3 grade-scan.py --import <file.csv>
                                       re-rank someone else's scan on your
                                       own costs — needs no eBay access

How it decides
--------------
Not by spread. Grade Edge leads with PSA 10 comp minus raw price, and sorting on
that ranks cards by their best case — which is the outcome you mostly do not
get. Their own worked example is a card with a 23.7% gem rate and a "+297% ROI"
headline; the expected value is a fraction of that, because three quarters of
the time you paid the grading fee to turn a $93 card into a $100 card.

So this ranks by expected value across the real grade distribution, and it will
not surface anything whose likely outcome is a large loss, however good the
spread looks. See gradescan/model.py.

What it needs
-------------
  eBay Browse API        free, self-serve at developer.ebay.com. Live listings.
  eBay Marketplace       free but approval-gated. Sold comps. Without it the
    Insights             scanner falls back to active PSA 10 asking prices,
                         which run high, and marks every such number ASK.
  Gem rates              typed in from GemRate card pages, which are free to
                         read. See gradescan/psa.py.

Credentials go in ~/.dtp-ebay.json, outside the repo, because the repo is public.
"""
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gradescan import ebay, importer, model, psa           # noqa: E402
from briefing_render import Section, render_text, render_html   # noqa: E402

TARGETS = os.path.join(HERE, 'gradescan', 'targets.json')
STATE = os.path.join(HERE, 'gradescan', 'scan-state.json')

# Asking prices are not sold prices. Sellers list optimistically and the ones
# that never sell stay up forever, so the visible asks skew high. When Insights
# is unavailable this haircut is applied to every comp taken from an active
# listing, and the result is still labelled ASK rather than presented as a comp.
ASK_HAIRCUT = 0.80

GRADED_RE = re.compile(r'\b(psa|bgs|sgc|cgc|beckett)\s*\.?\s*(10|9\.5|9|8)\b', re.I)
JUNK_RE = re.compile(
    r'\b(lot|reprint|custom|proxy|repack|mystery|digital|sticker|break|'
    r'random|spot|choose|you pick|read description|damaged|creased)\b', re.I)


def load_targets():
    with open(TARGETS) as fh:
        return json.load(fh)


def is_raw(title):
    return not GRADED_RE.search(title) and not JUNK_RE.search(title)


def looks_like(title, spec):
    """Every required word present, no excluded word present. Keeps a search for
    a Silver Prizm from matching a Gold Prizm that happened to rank."""
    t = title.lower()
    if not all(w.lower() in t for w in spec.get('must', [])):
        return False
    return not any(w.lower() in t for w in spec.get('must_not', []))


def comps_for(client, spec, use_sold):
    """Returns ({'p10','p9','p8'}, counts, mode)."""
    out, counts = {}, {}
    mode = 'SOLD' if use_sold else 'ASK'
    for key, grade in (('p10', 'PSA 10'), ('p9', 'PSA 9'), ('p8', 'PSA 8')):
        q = '%s %s' % (spec['query'], grade)
        try:
            if use_sold:
                items = client.sold(q, days=90, limit=100)
            else:
                items = client.active(q, limit=100)
        except ebay.NotApproved:
            return comps_for(client, spec, False)
        except ebay.EbayError as e:
            print('   ! comp lookup failed for %s: %s' % (q, e), file=sys.stderr)
            items = []

        # The search engine is loose; insist the grade is actually in the title.
        want = re.compile(r'\b(?:psa)\s*\.?\s*%s\b' % grade.split()[1], re.I)
        prices = [i['price'] + (0 if use_sold else i.get('shipping', 0))
                  for i in items
                  if want.search(i['title']) and looks_like(i['title'], spec)]
        med, n = model.summarise(prices)
        out[key] = med * (1.0 if use_sold else ASK_HAIRCUT)
        counts[key] = n
    return out, counts, mode


def scan(client, costs, policy, targets, use_sold, verbose=False):
    picks, unjudged, skipped = [], [], 0
    table = psa.load_table()

    for spec in targets:
        label = spec.get('label') or spec['query']
        print('-> %s' % label)

        comps, counts, mode = comps_for(client, spec, use_sold)
        if not comps.get('p10'):
            print('   no PSA 10 comp found, skipping')
            continue
        print('   comps %s: 10 $%.2f (n=%d)  9 $%.2f (n=%d)'
              % (mode, comps['p10'], counts['p10'], comps['p9'], counts['p9']))

        try:
            live = client.active(spec['query'],
                                 limit=spec.get('limit', 100),
                                 max_price=spec.get('max_price'))
        except ebay.EbayError as e:
            print('   ! live search failed: %s' % e, file=sys.stderr)
            continue

        cands = [i for i in live if is_raw(i['title']) and looks_like(i['title'], spec)]
        print('   %d live, %d plausibly raw' % (len(live), len(cands)))

        for it in cands:
            if it['price'] <= 0:
                continue
            rates, source = psa.lookup(it['title'] + ' ' + label, table)
            r = model.evaluate(it['price'], it.get('shipping', 0.0),
                               comps, rates, costs)
            row = dict(r, title=it['title'], url=it['url'], mode=mode,
                       seller=it['seller'], gem_source=source,
                       pop_total=rates['pop_total'], label=label,
                       gem_url=psa.search_url(label))

            if source is None:
                # No gem rate on file. Never recommended — the maths ran on an
                # assumption, and an assumption is not a reason to spend money.
                if r['spread'] > 60:
                    unjudged.append(row)
                continue

            reasons = policy.reasons_to_skip(r, counts, rates['pop_total'])
            if reasons:
                skipped += 1
                if verbose:
                    print('     skip %-40s %s' % (it['title'][:40], '; '.join(reasons)))
                continue
            picks.append(row)

    picks.sort(key=lambda x: -x['ev_profit'])
    unjudged.sort(key=lambda x: -x['spread'])
    return picks, unjudged, skipped


def money(v):
    return '${:,.2f}'.format(v)


def build_report(picks, unjudged, skipped, mode, insights):
    today = date.today()
    title = 'DUXBURY TRADING POST — grade scan   %s' % today
    meta = ('%d buy%s worth making' % (len(picks), '' if len(picks) == 1 else 's')
            if picks else 'nothing clears the bar today')
    sections = []

    if not insights:
        sections.append(Section(
            'Running on asking prices', tone='bad', text_prefix='!!',
            rows=[], empty=(
                'eBay Marketplace Insights is not approved on this account, so '
                'every comp below came from active listings rather than completed '
                'sales, discounted %d%% and marked ASK. Asks run high. Verify any '
                'card you act on against eBay sold before buying.'
                % int((1 - ASK_HAIRCUT) * 100))))

    if picks:
        sections.append(Section(
            'Buy candidates', tone='good',
            subtitle='ranked by expected value, not by spread',
            cols=[('EV', 'r'), ('ROI', 'r'), ('Buy', 'r'), ('All-in', 'r'),
                  ('PSA 10', 'r'), ('Gem', 'r'), ('If it 9s', 'r'), ('Card', 'l')],
            rows=[[('{:+,.2f}'.format(p['ev_profit']), 'good'),
                   '{:.0f}%'.format(p['ev_roi'] * 100),
                   money(p['acquire']),
                   money(p['all_in']),
                   money(p['p10']) + ('' if p['mode'] == 'SOLD' else ' ask'),
                   '{:.1f}%'.format(p['gem'] * 100),
                   ('{:+,.2f}'.format(p['downside']),
                    'bad' if p['downside'] < 0 else None),
                   p['title'][:52]]
                  for p in picks[:15]],
            footnote=('EV is across the real grade distribution, net of eBay fees '
                      'and a Ground Advantage label. "If it 9s" is the common '
                      'outcome, not the worst one.')))

    if unjudged:
        sections.append(Section(
            'Needs a gem rate', tone='warn',
            subtitle='wide spreads, but no population on file — not judged',
            cols=[('Spread', 'r'), ('Buy', 'r'), ('PSA 10', 'r'), ('Card', 'l')],
            rows=[[money(u['spread']), money(u['acquire']), money(u['p10']),
                   u['title'][:52]] for u in unjudged[:10]],
            footnote=('Look these up on gemrate.com and record them with: '
                      'python3 grade-scan.py --gem "<set words>" <10s> <9s> <8s>')))

    if not picks and not unjudged:
        sections.append(Section(
            'Nothing today', tone='muted', rows=[],
            empty=('%d listings were evaluated and rejected. That is the normal '
                   'result — the spread has to survive grading cost, freight, '
                   'eBay fees and the odds before it is a buy.' % skipped)))

    return title, meta, sections, [
        ('candidates', str(len(picks)), 'good' if picks else None),
        ('rejected', str(skipped), None),
        ('comps', mode, None),
    ]


def cmd_import(path):
    """Re-rank a third-party scan on your own numbers.

    Their breadth, your maths. Needs no eBay API access, so it works during a
    trial month or in place of one."""
    with open(os.path.expanduser(path)) as fh:
        rows, mapping, problems = importer.parse(fh.read())

    for p in problems:
        print('  ! %s' % p, file=sys.stderr)
    if not rows:
        sys.exit('Nothing usable in %s.' % path)

    print('read %d rows, mapped: %s\n'
          % (len(rows), ', '.join('%s<-%s' % (k, v) for k, v in sorted(mapping.items()))))

    cfg = load_targets()
    costs = model.Costs(**cfg.get('costs', {}))
    policy = model.Policy(**cfg.get('policy', {}))

    scored, rejected = [], []
    for row in rows:
        rates = importer.to_rates(row)
        r = model.evaluate(row['raw'], 0.0,
                           {'p10': row['p10'], 'p9': row['p9'], 'p8': row['p8']},
                           rates, costs)
        r['title'] = row['card']
        r['their_roi'] = (r['spread'] / row['raw']) if row['raw'] else 0
        # Comp depth is their problem, not ours — we cannot see their sample
        # size, so that check is waived and pop stands in for it.
        why = policy.reasons_to_skip(r, {'p10': 99, 'p9': 99}, rates['pop_total'] or 99)
        (scored if not why else rejected).append((r, why))

    scored.sort(key=lambda x: -x[0]['ev_profit'])
    rejected.sort(key=lambda x: -x[0]['spread'])

    title = 'DUXBURY TRADING POST — imported scan, re-ranked   %s' % date.today()
    sections = []
    if scored:
        sections.append(Section(
            'Survives your cost structure', tone='good',
            subtitle='ranked by expected value, not spread',
            cols=[('EV', 'r'), ('EV ROI', 'r'), ('Their ROI', 'r'), ('Raw', 'r'),
                  ('All-in', 'r'), ('Gem', 'r'), ('If it 9s', 'r'), ('Card', 'l')],
            rows=[[('{:+,.2f}'.format(r['ev_profit']), 'good'),
                   '{:.0f}%'.format(r['ev_roi'] * 100),
                   '{:.0f}%'.format(r['their_roi'] * 100),
                   money(r['acquire']), money(r['all_in']),
                   '{:.1f}%'.format(r['gem'] * 100),
                   ('{:+,.2f}'.format(r['downside']),
                    'bad' if r['downside'] < 0 else None),
                   r['title'][:44]] for r, _ in scored[:20]]))
    if rejected:
        sections.append(Section(
            'Looks good on spread, fails on the odds', tone='bad',
            subtitle='%d of %d rows' % (len(rejected), len(rows)),
            cols=[('Their ROI', 'r'), ('EV', 'r'), ('Gem', 'r'),
                  ('Why not', 'l'), ('Card', 'l')],
            rows=[['{:.0f}%'.format(r['their_roi'] * 100),
                   ('{:+,.2f}'.format(r['ev_profit']),
                    'bad' if r['ev_profit'] < 0 else None),
                   '{:.1f}%'.format(r['gem'] * 100),
                   '; '.join(why)[:40], r['title'][:36]]
                  for r, why in rejected[:20]],
            footnote=('Grade distributions below a 10 are estimated from the gem '
                      'rate — 70/22/8 across 9, 8 and below. Record real counts '
                      'with --gem for anything you act on.')))

    text = render_text(title, '%d of %d clear the bar' % (len(scored), len(rows)),
                       sections)
    print(text)
    with open(os.path.join(HERE, 'DTP-import-scan.txt'), 'w') as fh:
        fh.write(text + '\n')


def cmd_gem(args):
    """--gem "<set words>" <pop10> <pop9> <pop8>"""
    if len(args) < 4:
        sys.exit('usage: --gem "<set words>" <pop_10> <pop_9> <pop_8>')
    key = args[0].strip().lower()
    t = psa.load_table()
    t[key] = {'pop_10': int(args[1]), 'pop_9': int(args[2]), 'pop_8': int(args[3]),
              'source': 'gemrate', 'checked': str(date.today())}
    psa.save_table(t)
    r = psa._rates(t[key])
    print('recorded "%s" — gem rate %.1f%% across %d graded'
          % (key, r['gem'] * 100, r['pop_total']))


def main():
    argv = sys.argv[1:]

    if '--gem' in argv:
        return cmd_gem(argv[argv.index('--gem') + 1:])

    if '--import' in argv:
        i = argv.index('--import')
        if i + 1 >= len(argv):
            sys.exit('usage: --import <file.csv>')
        return cmd_import(argv[i + 1])

    try:
        client = ebay.Client(verbose='--verbose' in argv)
    except ebay.EbayError as e:
        sys.exit(str(e))

    insights = client.has_insights()
    if '--check' in argv:
        print('eBay Browse API           : ok')
        print('Marketplace Insights      : %s'
              % ('approved' if insights else
                 'NOT approved — comps will come from asking prices'))
        t = psa.load_table()
        print('Gem rates on file         : %d set%s'
              % (len(t), '' if len(t) == 1 else 's'))
        for k, v in sorted(t.items()):
            r = psa._rates(v)
            print('    %-38s %5.1f%%  (%d graded)' % (k, r['gem'] * 100, r['pop_total']))
        return

    cfg = load_targets()
    costs = model.Costs(**cfg.get('costs', {}))
    policy = model.Policy(**cfg.get('policy', {}))
    targets = cfg['targets']

    print('scanning %d target%s, comps from %s\n'
          % (len(targets), '' if len(targets) == 1 else 's',
             'completed sales' if insights else 'ASKING PRICES'))

    picks, unjudged, skipped = scan(client, costs, policy, targets,
                                    use_sold=bool(insights),
                                    verbose='--verbose' in argv)

    title, meta, sections, stats = build_report(
        picks, unjudged, skipped, 'sold' if insights else 'ask', insights)
    text = render_text(title, meta, sections)
    print('\n' + text)

    with open(os.path.join(HERE, 'DTP-grade-scan.txt'), 'w') as fh:
        fh.write(text + '\n')

    # Hand the result to the morning briefing rather than sending a second
    # email. Written as data, not prose, so the briefing renders it in its own
    # style. Decoupled on purpose: this scan makes a lot of API calls and can
    # be slow or fail, and neither should delay or break the briefing.
    save_latest(picks, unjudged, skipped, insights)

    if '--dry' not in argv:
        send(title, text, render_html(title, meta, sections, stats))


LATEST = os.path.join(HERE, 'gradescan', 'latest.json')


def save_latest(picks, unjudged, skipped, insights):
    payload = {
        'ran': date.today().isoformat(),
        'insights': bool(insights),
        'skipped': skipped,
        'picks': [{k: p[k] for k in
                   ('title', 'url', 'ev_profit', 'ev_roi', 'acquire', 'all_in',
                    'p10', 'gem', 'downside', 'mode')} for p in picks[:15]],
        'unjudged': [{k: u[k] for k in
                      ('title', 'url', 'spread', 'acquire', 'p10', 'gem_url')}
                     for u in unjudged[:8]],
    }
    try:
        with open(LATEST, 'w') as fh:
            json.dump(payload, fh, indent=1)
    except OSError as e:
        print('[could not save scan results: %s]' % e, file=sys.stderr)


def load_latest(max_age_hours=18):
    """Returns the last scan, or None if there is not a recent one. The age
    check matters: a stale list of "buy these now" is worse than no list, since
    good listings get bought within hours."""
    try:
        age = (__import__('time').time() - os.path.getmtime(LATEST)) / 3600.0
        if age > max_age_hours:
            return None
        with open(LATEST) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def send(subject, text, html):
    import urllib.request
    import urllib.error
    kp = os.path.expanduser('~/.dtp-briefing-key')
    if not os.path.exists(kp):
        print('[no ~/.dtp-briefing-key — not emailed]', file=sys.stderr)
        return
    body = json.dumps({'subject': subject, 'text': text, 'html': html})
    req = urllib.request.Request(
        'https://duxburytradingpost.com/api/briefing',
        data=body.encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8',
                 'X-DTP-Key': open(kp).read().strip(),
                 'User-Agent': 'DuxburyTradingPost-GradeScan/1.0 '
                               '(+https://duxburytradingpost.com)'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print('[emailed: HTTP %s]' % r.status, file=sys.stderr)
    except Exception as e:
        print('[email failed: %s]' % e, file=sys.stderr)


if __name__ == '__main__':
    main()
