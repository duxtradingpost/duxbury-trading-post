#!/usr/bin/env python3
"""Every card ever run through comp.py, replayed against the current code.

    python3 reports/comp-selftest.py [-v]

Run this after ANY change to comp.py. Nine live listings on 2026-09-15 turned up
eighteen real bugs, and two of them were regressions - a fix for one card quietly
broke a card that had worked an hour earlier:

  * tightening the parallel test to stop a /25 polluting the McMillan comp cut
    the Valdez from 7 matching sales to 2
  * adding the bare-card-code reader ('FFS-TS') made 'ON-CARD' a card number
  * reading the player from the title picked 'CPA-EV Refractor' as a name, so
    every Valdez comp had to contain the word 'refractor'

None of those were caught by thinking harder. They were caught by re-running the
earlier cards, by hand, and noticing a number had moved. This makes that
automatic, so the fixtures only ever grow and a fix can never silently undo one.

Each new card that gets comped should be added: save the sold rows into
reports/fixtures/<name>.json and add an entry to cases.json with the verdict that
was believed correct AT THE TIME. If a later fix changes one, that is not a
failure - it is a decision to make deliberately, and to record.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures')
VERBOSE = '-v' in sys.argv


def run(c):
    out = subprocess.run(
        [sys.executable, os.path.join(HERE, 'comp.py'), c['item'],
         '--sold', os.path.join(FIX, c['name'] + '.json'),
         '--price', str(c['price']), '--title', c['title'], '--no-log'],
        capture_output=True, text=True).stdout
    if 'NO SALES OF THIS EXACT CARD' in out:
        return 'NOSALES', None, out
    if 'NO VERDICT' in out:
        return 'NOVERDICT', None, out
    m = re.search(r'>>> (\w+)', out)
    n = re.search(r'comp \(median of \d+ sales\)\s+\$([\d,]+\.\d\d)', out)
    return (m.group(1) if m else '?',
            float(n.group(1).replace(',', '')) if n else None, out)


def main():
    cases = json.load(open(os.path.join(FIX, 'cases.json')))
    bad = 0
    for c in cases:
        call, comp, out = run(c)
        ok_call = call == c['expect']
        ok_comp = c['comp'] is None or (comp is not None and abs(comp - c['comp']) < 0.02)
        ok = ok_call and ok_comp
        bad += not ok
        mark = 'ok  ' if ok else 'FAIL'
        got = f'{call:9}' + (f' comp ${comp:,.2f}' if comp else '')
        want = f'{c["expect"]:9}' + (f' comp ${c["comp"]:,.2f}' if c['comp'] else '')
        print(f'{mark} {c["name"]:9} got {got:26}' + ('' if ok else f' want {want}'))
        if VERBOSE or not ok:
            print(f'       {c["why"]}')
        if not ok:
            print('\n'.join('       | ' + l for l in out.strip().splitlines()[-8:]))
    print(f'\n{len(cases) - bad}/{len(cases)} cases pass')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
