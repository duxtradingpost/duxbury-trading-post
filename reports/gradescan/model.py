"""
Scoring — the part that is actually a decision rather than a lookup.

Grade Edge's headline is "net spread": PSA 10 comp minus raw price. Sorting by
that ranks cards by their best case, and the best case is the one outcome you
mostly do not get. Their own sample row makes the point — Jalen Hurts 2020 Prizm
Silver, raw $93, PSA 10 $500, "+297% ROI", gem rate 23.7%. Run the odds and the
$374 spread is about $15-35 of expected value once grading, freight and eBay
fees come out, because three quarters of the time you paid $33 plus shipping to
turn a $93 card into a $100 card.

So this ranks by expected value, not spread, and it refuses to recommend
anything whose common outcome is a large loss. Two cards can have identical
spreads and completely different businesses behind them.

Everything here is arithmetic on numbers supplied by the caller. No network.
"""

# eBay's cut, matching the rest of the shop's maths.
FEE = 0.1325
PER_ORDER_LOW, PER_ORDER_HIGH = 0.30, 0.40
ESE, GROUND = 0.78, 6.07
ESE_MAX_ITEM = 20 - ESE

# A slab is about 0.3" thick, over the eBay Standard Envelope limit, so anything
# you grade ships Ground Advantage on the way out regardless of price.
SLAB_SHIP = GROUND

# What a PSA 7-or-below recovers against the raw price paid for it.
LOW_GRADE_RECOVERY = 0.5


def net_proceeds(price, shipping=None):
    """What lands in your account after eBay takes its cut and you buy a label."""
    if shipping is None:
        shipping = ESE if price <= ESE_MAX_ITEM else GROUND
    per = PER_ORDER_LOW if price <= 10 else PER_ORDER_HIGH
    return price * (1 - FEE) - per - shipping


class Costs(object):
    """Submission costs. Defaults are PSA's Value tier as advertised in 2026
    plus realistic freight; every one is overridable from the config."""

    def __init__(self, grade_fee=32.99, ship_to_psa=20.0, cards_per_sub=10,
                 return_ship=0.0, insurance_pct=0.01):
        self.grade_fee = grade_fee
        self.ship_to_psa = ship_to_psa      # per submission, not per card
        self.cards_per_sub = max(1, cards_per_sub)
        self.return_ship = return_ship
        self.insurance_pct = insurance_pct

    def per_card(self, declared_value):
        freight = (self.ship_to_psa / self.cards_per_sub) + self.return_ship
        return self.grade_fee + freight + declared_value * self.insurance_pct


def evaluate(raw_price, raw_shipping, comps, rates, costs):
    """comps: {'p10','p9','p8'} sold prices. rates: {'gem','nine','eight'}.

    Returns a dict of every number the report needs. Nothing is filtered here —
    filtering is a policy decision and lives in the caller."""
    p10 = float(comps.get('p10') or 0)
    p9 = float(comps.get('p9') or 0)
    # An 8 usually sells at or under raw. Falling back to the raw price rather
    # than to zero keeps the downside honest instead of theatrical.
    p8 = float(comps.get('p8') or 0) or raw_price

    acquire = raw_price + raw_shipping
    all_in = acquire + costs.per_card(p10)

    gem, nine, eight = rates['gem'], rates['nine'], rates['eight']

    # Expected value across the grade distribution, each outcome netted of the
    # fees you would pay selling at that grade.
    # A 7 or below is not a graded card you sell at a premium — it is a slab
    # with a bad number on it, and it moves at a steep discount to the raw copy
    # you started with. Valuing that tail at zero would be wrong; ignoring it
    # entirely, which is what dropping it from the distribution does, is worse.
    low = rates.get('low', 0.0)
    p_low = raw_price * LOW_GRADE_RECOVERY

    ev_net = (gem * net_proceeds(p10, SLAB_SHIP)
              + nine * net_proceeds(p9, SLAB_SHIP)
              + eight * net_proceeds(p8, SLAB_SHIP)
              + low * net_proceeds(p_low, SLAB_SHIP))

    ev_profit = ev_net - all_in
    upside = net_proceeds(p10, SLAB_SHIP) - all_in     # it 10s
    downside = net_proceeds(p9, SLAB_SHIP) - all_in    # the common case
    floor = net_proceeds(p8, SLAB_SHIP) - all_in       # it 8s

    # What you would clear flipping it raw, untouched. If grading does not beat
    # this it is not worth doing however good the spread looks.
    raw_flip = net_proceeds(raw_price * 1.15) - acquire

    return {
        'acquire': acquire,
        'all_in': all_in,
        'p10': p10, 'p9': p9, 'p8': p8,
        'gem': gem,
        'ev_profit': ev_profit,
        'ev_roi': ev_profit / all_in if all_in else 0.0,
        'upside': upside,
        'downside': downside,
        'floor': floor,
        'raw_flip': raw_flip,
        'edge_over_raw': ev_profit - raw_flip,
        'spread': p10 - acquire,        # what Grade Edge would show you
    }


class Policy(object):
    """The bar a candidate has to clear. Separate from the maths so it can be
    tightened without touching anything that computes."""

    def __init__(self, min_ev_profit=25.0, min_ev_roi=0.25,
                 max_downside=-60.0, min_comps=3, min_gem=0.15,
                 min_pop_total=25, max_all_in=400.0):
        self.min_ev_profit = min_ev_profit
        self.min_ev_roi = min_ev_roi
        self.max_downside = max_downside
        self.min_comps = min_comps
        self.min_gem = min_gem
        self.min_pop_total = min_pop_total
        self.max_all_in = max_all_in

    def reasons_to_skip(self, r, comp_counts, pop_total):
        """Returns a list of reasons. Empty list means it passes."""
        out = []
        if r['ev_profit'] < self.min_ev_profit:
            out.append('EV only %+.2f' % r['ev_profit'])
        if r['ev_roi'] < self.min_ev_roi:
            out.append('EV ROI %.0f%%' % (r['ev_roi'] * 100))
        if r['downside'] < self.max_downside:
            out.append('a 9 loses %.2f' % abs(r['downside']))
        if r['gem'] < self.min_gem:
            out.append('gem rate %.1f%%' % (r['gem'] * 100))
        if pop_total < self.min_pop_total:
            out.append('only %d graded, thin pop' % pop_total)
        if r['all_in'] > self.max_all_in:
            out.append('all-in %.2f over cap' % r['all_in'])
        if r['edge_over_raw'] <= 0:
            out.append('flipping it raw beats grading')
        for k, label in (('p10', 'PSA 10'), ('p9', 'PSA 9')):
            if comp_counts.get(k, 0) < self.min_comps:
                out.append('only %d %s comps' % (comp_counts.get(k, 0), label))
        return out


def summarise(prices):
    """Median, not mean. One shill-priced outlier should not move a comp, and
    with the handful of sales these searches return it easily would."""
    vals = sorted(p for p in prices if p and p > 0)
    if not vals:
        return 0.0, 0
    n = len(vals)
    mid = n // 2
    med = vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0
    return med, n
