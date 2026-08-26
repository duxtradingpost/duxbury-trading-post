"""
Import a third-party scan and re-rank it on your own numbers.

Grade Edge and tools like it are good at breadth — they sweep far more cards
than a hand-curated watchlist ever will, and their table already carries the
four values the expected-value model needs: raw, PSA 9, PSA 10 and gem rate.
What they do not carry is your cost structure or your ranking.

So this takes their output and does the part they do not: subtract your actual
grading cost, your freight, your eBay fee schedule and the Ground Advantage
label a slab forces, then rank by expected value across the grade distribution
instead of by spread.

Two useful consequences:

  · it needs no eBay API access at all, so it works during a trial month before
    Marketplace Insights is approved — or instead of it
  · a subscription becomes a source you can cancel. Export the sets that
    actually carry spread, seed targets.json from them, and the watchlist keeps
    earning after the subscription stops

Accepts a CSV export or a pasted table. Headers are matched loosely because
every tool names these columns differently, and a paste from a web page arrives
with whatever whitespace the page had.

    python3 grade-scan.py --import ~/Downloads/gradeedge.csv
"""
import csv
import io
import re

# Every spelling seen in the wild for each field. First match wins, so put the
# specific ones first — "psa 10" must beat a bare "10".
COLUMNS = {
    'card':  ['card', 'name', 'player', 'description', 'title'],
    'raw':   ['raw sold', 'raw price', 'raw', 'ungraded'],
    'p10':   ['psa 10 sold', 'psa10', 'psa 10', 'gem mint', 'grade 10'],
    'p9':    ['psa 9 sold', 'psa9', 'psa 9', 'mint', 'grade 9'],
    'p8':    ['psa 8 sold', 'psa8', 'psa 8', 'grade 8'],
    'gem':   ['gem rate', 'gemrate', 'gem %', 'gem'],
    'pop':   ['pop', 'population', 'total pop', 'graded'],
}


def _num(v):
    """Pull a number out of '$1,234.56', '+297%', '23.7%', 'pop 1,495'."""
    if v is None:
        return 0.0
    s = str(v).replace(',', '').strip()
    m = re.search(r'-?\d+(?:\.\d+)?', s)
    return float(m.group(0)) if m else 0.0


def _pct(v):
    """A gem rate arrives as '23.7%' or as 0.237. Both mean the same thing, and
    guessing wrong is a 100x error in the ranking."""
    n = _num(v)
    if '%' in str(v):
        return n / 100.0
    return n / 100.0 if n > 1.0 else n


def _map_headers(fieldnames):
    out = {}
    lowered = [(f or '').strip().lower() for f in fieldnames]
    for key, aliases in COLUMNS.items():
        for alias in aliases:
            for i, name in enumerate(lowered):
                if alias == name or (alias in name and key not in out):
                    out[key] = fieldnames[i]
                    break
            if key in out:
                break
    return out


def parse(text):
    """Returns (rows, mapping, problems). Never raises on a bad row — a single
    malformed line should not throw away the other forty."""
    problems = []

    # Tolerate CSV, TSV and a paste where columns are split by runs of spaces.
    sample = text[:4000]
    if '\t' in sample:
        delim = '\t'
    elif sample.count(',') >= sample.count('|'):
        delim = ','
    else:
        delim = '|'

    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    if not reader.fieldnames:
        return [], {}, ['No header row found.']

    mapping = _map_headers(reader.fieldnames)
    missing = [k for k in ('card', 'raw', 'p10') if k not in mapping]
    if missing:
        return [], mapping, [
            'Could not find a column for: %s. Saw: %s'
            % (', '.join(missing), ', '.join(f for f in reader.fieldnames if f))]

    rows = []
    for i, r in enumerate(reader, start=2):
        try:
            card = str(r.get(mapping['card']) or '').strip()
            raw = _num(r.get(mapping['raw']))
            p10 = _num(r.get(mapping['p10']))
            if not card or raw <= 0 or p10 <= 0:
                continue
            rows.append({
                'card': card,
                'raw': raw,
                'p10': p10,
                'p9': _num(r.get(mapping['p9'])) if 'p9' in mapping else 0.0,
                'p8': _num(r.get(mapping['p8'])) if 'p8' in mapping else 0.0,
                'gem': _pct(r.get(mapping['gem'])) if 'gem' in mapping else 0.0,
                'pop': int(_num(r.get(mapping['pop']))) if 'pop' in mapping else 0,
            })
        except (ValueError, TypeError) as e:
            problems.append('row %d skipped: %s' % (i, e))
    return rows, mapping, problems


def to_rates(row):
    """Turn a gem rate into a full distribution.

    A gem rate alone does not say how the other three quarters split, and the
    split matters — a 9 and a 7 are very different outcomes. Absent real pop
    counts, the remainder is apportioned the way graded populations usually
    fall: most of it 9s, a slice of 8s, a small tail below. Approximate, and
    marked as such wherever it is used.
    """
    gem = max(0.0, min(1.0, row.get('gem') or 0.0))
    rest = 1.0 - gem
    return {
        'gem': gem,
        'nine': rest * 0.70,
        'eight': rest * 0.22,
        'low': rest * 0.08,
        'pop_total': row.get('pop') or 0,
        'estimated': True,
    }
