#!/usr/bin/env python3
"""Why did this card not get a price? Prints the query, every candidate
SportsCardsPro returned, and the exact rule that rejected each one.

    python3 reports/scp-why.py "2026 Topps Tribute Payton Tolle #4 Orange /25 RC Red Sox"
"""
import importlib.util, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('scp', os.path.join(HERE, 'scp-comps.py'))
m = importlib.util.module_from_spec(spec)
argv, sys.argv = sys.argv, ['scp']
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass
finally:
    sys.argv = argv

title = sys.argv[1]
sport = sys.argv[2] if len(sys.argv) > 2 else None
q, short = m.query_for(title)
print(f'TITLE  {title}')
print(f'QUERY  {q!r}')
prods = m.api_products(q, m.token())
if prods is not None and not any(m.scp_matches(p, title, sport)[0] for p in prods) and short != q:
    print(f'  (long query matched nothing; falling back to {short!r})')
    q = short; prods = m.api_products(q, m.token())
if prods is None:
    sys.exit('  request failed')
print(f'{len(prods)} products returned; our parallel words = {sorted(m.parallel_terms(title.partition("#")[2])) or "base"}\n')
kept = 0
for p in prods[:30]:
    ok, why = m.scp_matches(p, title, sport)
    kept += ok
    name = f"{p.get('console-name','')} | {p.get('product-name','')}"
    print(f"  {'KEEP' if ok else 'drop'}  {name[:74]:<74} {'' if ok else why}")
print(f'\n{kept} survived')
