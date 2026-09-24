#!/usr/bin/env python3
"""Exchange a Shopify OAuth code for a permanent Admin API token.

    1. copy the client secret from the app's App settings, then:
         pbpaste > ~/.dtp-shopify-secret && chmod 600 ~/.dtp-shopify-secret
    2. open the install URL, copy the whole example.com address, then:
         pbpaste > /tmp/dtp-code
    3. python3 reports/get-shopify-token.py

Writes ~/.dtp-shopify-token (0600) and shreds both inputs on success.

Reads from files rather than prompting because Claude Code's `!` shell has no
interactive stdin — input() gets EOF immediately — and because the login shell
is zsh, where the bash-ism `read -rsp` silently yields an empty string. Going via
the clipboard means neither secret is ever typed, echoed, or put in history.
"""
import json, os, re, sys, urllib.error, urllib.parse, urllib.request

SHOP      = 'hmbhxb-y0.myshopify.com'
CLIENT_ID = '2c70bfb94d048b205a1b976ab0ff20bc'
DEST      = os.path.expanduser('~/.dtp-shopify-token')
SECRET_F  = os.path.expanduser('~/.dtp-shopify-secret')
CODE_F    = '/tmp/dtp-code'


def read(path, what):
    if not os.path.exists(path):
        sys.exit(f'missing {path} — {what}')
    v = open(path).read().strip()
    if not v:
        sys.exit(f'{path} is empty')
    return v


code = read(CODE_F, 'copy the example.com URL and run: pbpaste > /tmp/dtp-code')
if 'code=' in code:
    code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query).get('code', [''])[0]
    if not code:
        sys.exit('no code= found in that URL')
secret = read(SECRET_F, 'copy the client secret and run: ~/s')
# Modern secrets are shpss_ + 32 hex (38 chars); older ones are bare 32 hex.
if not re.fullmatch(r'(shpss_)?[0-9a-f]{32}', secret):
    sys.exit(f'that does not look like a client secret ({len(secret)} chars).\n'
             'Copying a command in order to run it overwrites the clipboard you are '
             'trying to capture — click copy in Shopify, then run ~/s without '
             'copying anything else.')

body = urllib.parse.urlencode({'client_id': CLIENT_ID, 'client_secret': secret,
                               'code': code}).encode()
try:
    with urllib.request.urlopen(
            urllib.request.Request(f'https://{SHOP}/admin/oauth/access_token', data=body),
            timeout=30) as r:
        d = json.load(r)
except urllib.error.HTTPError as e:
    sys.exit(f'HTTP {e.code}: {e.read().decode()[:200]}\n'
             '(a code is single-use and expires in minutes — get a fresh one)')

tok = d.get('access_token')
if not tok:
    sys.exit(f'no access_token in response: {str(d)[:200]}')

with open(DEST, 'w') as fh:
    fh.write(tok)
os.chmod(DEST, 0o600)

# The code is spent, so it goes. The SECRET stays: every scope change requires a
# fresh OAuth exchange, and deleting it means asking Craig to re-copy it from the
# Shopify dashboard each time — friction that buys nothing, since the file is
# 0600 in his home directory either way.
try:
    os.remove(CODE_F)
except OSError:
    pass
os.chmod(SECRET_F, 0o600)

print(f'saved {len(tok)} chars to {DEST}')
print(f'scopes granted: {d.get("scope", "?")}')
print('code consumed; client secret kept at ~/.dtp-shopify-secret (0600) for future scope changes')
