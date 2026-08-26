"""
eBay API client — stdlib only, no requests.

Two endpoints matter here and they are not equally available:

  Browse            active listings. Free, self-serve keys, no approval.
                    This is "what can I buy right now".

  Marketplace       completed sales for the last 90 days. Requires eBay to
  Insights          approve your application, which they grant selectively.
                    This is "what does it actually sell for".

The scanner is built so it degrades instead of failing. With Insights it
compares a live raw price against real PSA 10 sold prices. Without it, it falls
back to the *asking* prices of active PSA 10 listings, which run high — sellers
list optimistically and the ones that never sell stay up forever, so the visible
asks skew above the market. Every number derived that way is marked ASK and
discounted, and the report says so rather than quietly presenting a guess as a
comp.

Credentials live in ~/.dtp-ebay.json, outside the repo:

    {"client_id": "...", "client_secret": "..."}

Not in the repo, because the repo is public.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

CREDS_PATH = os.path.expanduser('~/.dtp-ebay.json')

OAUTH_URL = 'https://api.ebay.com/identity/v1/oauth2/token'
BROWSE_URL = 'https://api.ebay.com/buy/browse/v1/item_summary/search'
INSIGHTS_URL = ('https://api.ebay.com/buy/marketplace_insights/v1_beta'
                '/item_sales/search')

SCOPE_BASE = 'https://api.ebay.com/oauth/api_scope'
SCOPE_INSIGHTS = 'https://api.ebay.com/oauth/api_scope/buy.marketplace.insights'

MARKETPLACE = 'EBAY_US'
UA = 'DuxburyTradingPost-GradeScan/1.0 (+https://duxburytradingpost.com)'


class EbayError(RuntimeError):
    pass


class NotApproved(EbayError):
    """Raised when the account has no Marketplace Insights grant. Expected, and
    handled by falling back — not a bug."""


def load_creds():
    if not os.path.exists(CREDS_PATH):
        raise EbayError(
            'No eBay credentials. Create %s containing '
            '{"client_id": "...", "client_secret": "..."} — get the keys from '
            'developer.ebay.com under your production app.' % CREDS_PATH)
    with open(CREDS_PATH) as fh:
        c = json.load(fh)
    if not c.get('client_id') or not c.get('client_secret'):
        raise EbayError('%s needs both client_id and client_secret.' % CREDS_PATH)
    return c


class Client(object):
    def __init__(self, verbose=False):
        self.creds = load_creds()
        self.verbose = verbose
        self._tokens = {}          # scope string -> (token, expires_at)
        self.insights_ok = None    # None = untested, True/False after first try

    # --- auth ----------------------------------------------------------------

    def _token(self, scope):
        tok, exp = self._tokens.get(scope, (None, 0))
        # 60s of slack so a token cannot expire between the check and the call.
        if tok and time.time() < exp - 60:
            return tok

        basic = base64.b64encode(
            ('%s:%s' % (self.creds['client_id'], self.creds['client_secret']))
            .encode('utf-8')).decode('ascii')
        body = urllib.parse.urlencode({
            'grant_type': 'client_credentials',
            'scope': scope,
        }).encode('utf-8')
        req = urllib.request.Request(OAUTH_URL, data=body, headers={
            'Authorization': 'Basic ' + basic,
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': UA,
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', 'replace')[:300]
            # An unapproved scope fails at the token step, not the call.
            if scope == SCOPE_INSIGHTS:
                raise NotApproved(detail)
            raise EbayError('token request failed: HTTP %s %s' % (e.code, detail))

        tok = data['access_token']
        self._tokens[scope] = (tok, time.time() + int(data.get('expires_in', 7200)))
        return tok

    # --- requests ------------------------------------------------------------

    def _get(self, url, params, scope, extra_headers=None):
        qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        headers = {
            'Authorization': 'Bearer ' + self._token(scope),
            'X-EBAY-C-MARKETPLACE-ID': MARKETPLACE,
            'Accept': 'application/json',
            'User-Agent': UA,
        }
        headers.update(extra_headers or {})
        req = urllib.request.Request(url + '?' + qs, headers=headers)
        if self.verbose:
            print('  GET %s?%s' % (url.rsplit('/', 1)[-1], qs[:160]))
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=45) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                detail = e.read().decode('utf-8', 'replace')[:300]
                if e.code in (403, 401) and 'insights' in url:
                    raise NotApproved(detail)
                # 429 is a rate limit; backing off and retrying is the whole fix.
                if e.code in (429, 500, 502, 503) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise EbayError('HTTP %s from %s: %s' % (e.code, url, detail))
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise EbayError('network error: %s' % e)

    # --- the two searches ----------------------------------------------------

    def active(self, query, limit=100, max_price=None, buy_it_now=True):
        """Live listings — what is actually buyable right now."""
        filters = ['itemLocationCountry:US']
        if buy_it_now:
            # An auction's current bid is not a price you can pay, so mixing
            # them in would make every auction look like a bargain.
            filters.append('buyingOptions:{FIXED_PRICE}')
        if max_price:
            filters.append('price:[..%s],priceCurrency:USD' % max_price)

        params = {
            'q': query,
            'limit': str(min(limit, 200)),
            'filter': ','.join(filters),
        }
        data = self._get(BROWSE_URL, params, SCOPE_BASE)
        return [_norm_active(i) for i in data.get('itemSummaries') or []]

    def sold(self, query, days=90, limit=100):
        """Completed sales. Raises NotApproved if the app lacks the grant."""
        end = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
        start = time.strftime('%Y-%m-%dT%H:%M:%S.000Z',
                              time.gmtime(time.time() - days * 86400))
        params = {
            'q': query,
            'limit': str(min(limit, 200)),
            'filter': 'lastSoldDate:[%s..%s]' % (start, end),
        }
        try:
            data = self._get(INSIGHTS_URL, params, SCOPE_INSIGHTS)
        except NotApproved:
            self.insights_ok = False
            raise
        self.insights_ok = True
        return [_norm_sold(i) for i in data.get('itemSales') or []]

    def has_insights(self):
        """One cheap probe, cached, so the scanner can report which mode it ran
        in without every lookup re-discovering the same 403."""
        if self.insights_ok is None:
            try:
                self.sold('topps chrome', days=7, limit=1)
            except NotApproved:
                pass
            except EbayError:
                # A network blip should not be recorded as "not approved".
                return None
        return self.insights_ok


def _price(node):
    try:
        return float((node or {}).get('value') or 0)
    except (TypeError, ValueError):
        return 0.0


def _norm_active(i):
    ship = 0.0
    for opt in i.get('shippingOptions') or []:
        ship = _price(opt.get('shippingCost'))
        break
    return {
        'id': i.get('itemId'),
        'title': i.get('title') or '',
        'price': _price(i.get('price')),
        'shipping': ship,
        'url': i.get('itemWebUrl') or '',
        'condition': i.get('condition') or '',
        'seller': (i.get('seller') or {}).get('username') or '',
        'image': (i.get('image') or {}).get('imageUrl') or '',
    }


def _norm_sold(i):
    return {
        'id': i.get('itemId'),
        'title': i.get('title') or '',
        'price': _price(i.get('lastSoldPrice')),
        'date': i.get('lastSoldDate') or '',
        'url': i.get('itemWebUrl') or '',
    }
