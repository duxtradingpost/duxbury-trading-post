"""
Gem rate — the odds a raw card actually comes back a 10.

This is the number the whole tool turns on, and it is the one number without a
free API. PSA's own public API covers cert verification only — the population
report is on their site but not exposed as an endpoint. GemRate has a proper
API, but it is partner-tier with no self-serve signup or published price.

What GemRate does give away is the card pages themselves, free to read, with
the full grade distribution on them. So this keeps a local table you fill in
from those pages by hand. Not scraped — read and typed, the way you would look
up any comp. That is a better fit than it sounds:

  · pop numbers move slowly. A gem rate looked up once is good for months.
  · the scanner only needs a rate for candidates that already cleared the
    spread filter — a handful a week, not thousands.
  · looking one up is a 30-second visit to a GemRate card page, which prints
    the PSA row as POP / GEMS+ / 9 / 8 — the three numbers below, in order.

A card with no entry is not dropped. It is reported separately as "needs a gem
rate", with the lookup URL, so the scanner tells you what it could not judge
instead of silently judging it wrong.

The table lives in gem-rates.json next to this file:

    {
      "2020 panini prizm silver": {
        "pop_10": 355, "pop_9": 906, "pop_8": 172,
        "source": "gemrate", "checked": "2026-08-26"
      }
    }

Keys are matched loosely — a key matches a card title when every word in the
key appears in the title. So one entry for a set covers every card in it, which
is the right granularity: gem rate is a property of how a set was printed and
cut far more than of which player is on the card.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE = os.path.join(HERE, 'gem-rates.json')

POP_URL = 'https://www.gemrate.com/universal-search'

# Used when a set has no entry at all. Deliberately pessimistic: assuming a card
# gems until proven otherwise is how you talk yourself into a bad submission.
# Nothing is recommended on this basis — it exists so the maths still runs and
# the card lands in the "needs a gem rate" list.
ASSUMED = {'pop_10': 20, 'pop_9': 55, 'pop_8': 20, 'pop_low': 5}


def load_table():
    if not os.path.exists(TABLE):
        return {}
    try:
        with open(TABLE) as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return {}


def save_table(t):
    with open(TABLE, 'w') as fh:
        json.dump(t, fh, indent=1, sort_keys=True)


def _words(s):
    return set(re.findall(r'[a-z0-9]+', s.lower()))


def lookup(title, table=None):
    """Returns (rates, source) where rates has gem/nine/eight as fractions.

    source is the matched key, or None when nothing matched and ASSUMED was
    used. Callers are expected to treat source=None as "unjudged"."""
    table = load_table() if table is None else table
    tw = _words(title)

    # Longest matching key wins — "2020 panini prizm silver" should beat a
    # broader "panini prizm" entry when both match.
    best, best_len = None, -1
    for key, val in table.items():
        kw = _words(key)
        if kw and kw <= tw and len(kw) > best_len:
            best, best_len = (key, val), len(kw)

    if best is None:
        return _rates(ASSUMED), None
    return _rates(best[1]), best[0]


def _rates(entry):
    """pop_low is everything 7 and below. Including it matters twice: it is the
    difference between this gem rate and the one printed on the GemRate page,
    and those cards are worth well under the raw price you paid, so dropping
    them flatters the expected value."""
    ten = float(entry.get('pop_10') or 0)
    nine = float(entry.get('pop_9') or 0)
    eight = float(entry.get('pop_8') or 0)
    low = float(entry.get('pop_low') or 0)
    total = ten + nine + eight + low
    if total <= 0:
        total = 1.0
    return {
        'gem': ten / total,
        'nine': nine / total,
        'eight': eight / total,
        'low': low / total,
        'pop_total': int(ten + nine + eight + low),
    }


def search_url(title):
    """Where to go to fill in a missing entry. GemRate's universal search
    covers PSA, BGS, SGC and CGC in one page; the PSA row is the one that
    matters here since PSA 10 is what the comps are priced against."""
    import urllib.parse
    return POP_URL + '?' + urllib.parse.urlencode({'q': title[:80]})
