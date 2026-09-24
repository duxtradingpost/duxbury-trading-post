#!/usr/bin/env python3
"""Upload paired card scans straight to Heystack, skipping their broken scanner app.

    python3 reports/heystack-upload.py                    # dry run, shows the pairs it found
    python3 reports/heystack-upload.py --apply            # actually upload
    python3 reports/heystack-upload.py --apply --folder "Sept rip"   # override stack name

Why this exists
---------------
Heystack Scanner Connect fails on the fi-8170 with MAC-004 "Duplex scanning
requires a scanner with an ADF document feeder" (exit 2). It is THEIR bug, on
THEIR officially supported scanner: the PFU driver fires a phantom Flatbed
callback before the real DocumentFeeder one, and their delegate treats the first
callback as failure and gives up. Proven 2026-09-20 by probing ICA directly --
the device reports availableFunctionalUnitTypes = [DocumentFeeder],
supportsDuplexScanning = YES, documentLoaded = YES. A DYLD shim got their helper
to a clean `{"pairs": []}` but zero pages, because the functional unit the driver
hands back is detached from the hardware. Their macOS build has not been updated
since 2026-03-16 (checked against the live DMG, byte-identical).

Meanwhile Apple's Image Capture drives the very same scanner over the very same
ICA interface without complaint, at 600dpi -- better than the 300dpi their app
produces. So the scan half was never the problem. The only thing their app did
that we could not was the upload.

This script is that upload. The contract was read out of their own bytecode
(hs_extract/main2, function `upload_images`):

    POST https://api.heystack.tech/upload_card_pw   (timeout 60s)
    files: front = ('front_<tag>.jpg', <jpeg bytes>, 'image/jpeg')
           back  = ('back_<tag>.jpg',  <jpeg bytes>, 'image/jpeg')
    data:  email, password, folder_name, no_crop
    tag:   caller-supplied, else int(time.time() * 1000)

Note `no_crop` is INVERTED relative to the GUI checkbox: ticking "Use Ricoh
cropping" sends no_crop=False. That checkbox is about server-side cropping and
has nothing to do with the scanner, which is why ticking it never fixed MAC-004.

The pipeline
------------
    1. Scan in Image Capture with the card settings (600dpi, A6, duplex on,
       multifeed OFF, prepick OFF, blank-page-skip OFF)
    2. python3 reports/scan-rename.py --stack N --apply
    3. python3 reports/heystack-upload.py --apply

Credentials
-----------
Account and stack name live in ~/.heystack.conf (no secret, safe to back up):

    email=info@duxburytradingpost.com
    folder_name=test

The password lives in the macOS login keychain, stored once with:

    security add-generic-password -U -a "<email>" -s "heystack" -w

`-w` with no value PROMPTS, so the password is never an argument, never in shell
history, and never on disk in the clear. Use `-U`: it overwrites an existing
item, and without it a second attempt dies with "The specified item already
exists in the keychain." The prompt echoes nothing, so pressing Enter on an
empty line stores an EMPTY password and still exits 0 -- this script treats
that as "no password" and tells you to re-run. Their own ~/config.txt (three plaintext
lines) is still accepted as a fallback for an existing setup, but the keychain is
the path to use. This script only ever reads credentials and never prints them.
"""

import argparse, json, os, re, ssl, subprocess, sys, time, urllib.request, urllib.error

API_URL = 'https://api.heystack.tech/upload_card_pw'
TIMEOUT_S = 60
CONFIG = os.path.expanduser('~/config.txt')          # their plaintext format (fallback)
ACCOUNT_FILE = os.path.expanduser('~/.heystack.conf')  # email + folder only, no secret
KEYCHAIN_SERVICE = 'heystack'
SCAN_DIR = os.path.expanduser('~/Pictures/Card Scans')

PAIR_RE = re.compile(r'^card-(\d+)-(front|back)\.(jpe?g)$', re.I)


def _keychain_password(email):
    """Read the Heystack password from the login keychain.

    Preferred over their config.txt, which stores the password in PLAINTEXT in
    the home folder. The password never appears in this repo, in a dotfile, in
    shell history, or in any log -- it is typed once into `security -w`, which
    prompts rather than taking it as an argument.
    """
    try:
        out = subprocess.run(
            ['security', 'find-generic-password', '-s', KEYCHAIN_SERVICE,
             '-a', email, '-w'],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def load_config():
    """(email, password, folder_name).

    Account and stack name come from ~/.heystack.conf (no secret in it, safe to
    read and back up). The password comes from the keychain. Their own
    plaintext config.txt is accepted as a fallback so an existing setup keeps
    working, but it is not the recommended path.
    """
    email = folder = None
    if os.path.exists(ACCOUNT_FILE):
        with open(ACCOUNT_FILE, encoding='utf-8') as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln or ln.startswith('#') or '=' not in ln:
                    continue
                k, v = ln.split('=', 1)
                if k.strip() == 'email':
                    email = v.strip()
                elif k.strip() == 'folder_name':
                    folder = v.strip()

    if email:
        pwd = _keychain_password(email)
        if pwd:
            return email, pwd, folder
        sys.exit(
            f'No Heystack password in the keychain for {email}.\n'
            f'Store it once (you type it, it is never passed as an argument):\n\n'
            f'  security add-generic-password -U -a "{email}" '
            f'-s "{KEYCHAIN_SERVICE}" -w\n\n'
            f'-w prompts twice and echoes nothing, so an empty Enter stores an\n'
            f'EMPTY password and `security` still exits 0 -- which looks exactly\n'
            f'like this message. -U overwrites the existing item; without it the\n'
            f'second attempt fails with "The specified item already exists".\n')

    # Fallback: their plaintext format, three lines.
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding='utf-8') as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
        if len(lines) < 3:
            sys.exit(f'{CONFIG} must have 3 lines: email, pwd, folder_name')
        return lines[0], lines[1], lines[2]

    sys.exit(f'No credentials. Create {ACCOUNT_FILE} with:\n'
             f'  email=you@example.com\n  folder_name=test\n'
             f'then store the password in the keychain:\n'
             f'  security add-generic-password -a "you@example.com" '
             f'-s "{KEYCHAIN_SERVICE}" -w')


def find_pairs(folder):
    """Collect card-NNN-front/back sets that scan-rename.py has already made.

    Deliberately NOT re-implementing the pairing. scan-rename.py orders by
    st_birthtime because Image Capture's filenames do not sort into feed order,
    and duplicating that logic here would be a second place to get it wrong.
    """
    sides = {}
    for name in os.listdir(folder):
        m = PAIR_RE.match(name)
        if m:
            sides.setdefault(m.group(1), {})[m.group(2).lower()] = os.path.join(folder, name)
    pairs, orphans = [], []
    for num in sorted(sides):
        s = sides[num]
        if 'front' in s and 'back' in s:
            pairs.append((num, s['front'], s['back']))
        else:
            orphans.append((num, s))
    return pairs, orphans


def _multipart(fields, files):
    """Build a multipart/form-data body with no third-party dependency.

    `requests` is not installed on the system python and this has to run from a
    launchd job, so it is hand-rolled rather than adding an install step.
    """
    boundary = f'----DTPHeystack{int(time.time()*1000)}'
    out = bytearray()
    for k, v in fields.items():
        out += f'--{boundary}\r\n'.encode()
        out += f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
        out += f'{v}\r\n'.encode()
    for k, (fname, blob, ctype) in files.items():
        out += f'--{boundary}\r\n'.encode()
        out += (f'Content-Disposition: form-data; name="{k}"; '
                f'filename="{fname}"\r\n').encode()
        out += f'Content-Type: {ctype}\r\n\r\n'.encode()
        out += blob + b'\r\n'
    out += f'--{boundary}--\r\n'.encode()
    return bytes(out), f'multipart/form-data; boundary={boundary}'


def upload(front, back, email, pwd, folder_name, use_cropping, tag):
    files = {
        'front': (f'front_{tag}.jpg', open(front, 'rb').read(), 'image/jpeg'),
        'back':  (f'back_{tag}.jpg',  open(back, 'rb').read(),  'image/jpeg'),
    }
    data = {
        'email': email,
        'password': pwd,
        'folder_name': folder_name,
        # inverted on purpose -- see the module docstring
        'no_crop': 'False' if use_cropping else 'True',
    }
    body, ctype = _multipart(data, files)
    req = urllib.request.Request(API_URL, data=body, method='POST')
    req.add_header('Content-Type', ctype)
    req.add_header('Content-Length', str(len(body)))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S,
                                    context=ssl.create_default_context()) as r:
            return r.status, r.read().decode('utf-8', 'replace')[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')[:400]
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'


def main():
    ap = argparse.ArgumentParser(description='Upload paired card scans to Heystack.')
    ap.add_argument('folder', nargs='?', default=SCAN_DIR,
                    help='folder of card-NNN-front/back files (default: ~/Pictures/Card Scans)')
    ap.add_argument('--folder-name', help='Heystack stack name (default: line 3 of config.txt)')
    # DEFAULT IS NO SERVER-SIDE CROP (no_crop=True), changed 2026-09-21.
    # Image Capture has already cropped these tight to the card at 600dpi.
    # Heystack's crop is tuned for their own app's 300dpi framing, so letting it
    # run crops an already-cropped card and slices into the art. --no-cropping is
    # kept as an accepted no-op so older callers keep working.
    ap.add_argument('--no-cropping', action='store_true',
                    help='(default, kept for compatibility) send no_crop=True')
    ap.add_argument('--cropping', action='store_true',
                    help='OPT IN to Heystack server-side cropping (no_crop=False). '
                         'Only for images that are NOT already cropped to the card.')
    ap.add_argument('--limit', type=int, help='upload at most N pairs (useful for a first test)')
    ap.add_argument('--apply', action='store_true', help='actually upload (default is a dry run)')
    a = ap.parse_args()

    if not os.path.isdir(a.folder):
        sys.exit(f'No such folder: {a.folder}')
    email, pwd, cfg_folder = load_config()
    stack = a.folder_name or cfg_folder

    pairs, orphans = find_pairs(a.folder)
    if orphans:
        print(f'!! {len(orphans)} card(s) missing a side — NOT uploading these:', file=sys.stderr)
        for num, s in orphans:
            print(f'   card-{num}: has {", ".join(sorted(s))}', file=sys.stderr)
        print('   Run scan-rename.py --stack N first; a missing side means a misfeed.\n',
              file=sys.stderr)
    if not pairs:
        sys.exit('No complete front/back pairs found. Run scan-rename.py --apply first.')

    if a.limit:
        pairs = pairs[:a.limit]
    print(f'{len(pairs)} pair(s) -> stack "{stack}" as {email}')
    if not a.apply:
        for num, f, b in pairs:
            print(f'  would upload card-{num}: {os.path.basename(f)} + {os.path.basename(b)}')
        print('\nDry run. Add --apply to upload.')
        return 0

    ok = fail = 0
    for num, f, b in pairs:
        tag = f'{int(time.time()*1000)}-{num}'
        status, body = upload(f, b, email, pwd, stack, a.cropping, tag)
        if status == 200:
            ok += 1
            print(f'  card-{num}: OK')
        else:
            fail += 1
            print(f'  card-{num}: FAILED [{status}] {body}', file=sys.stderr)
    print(f'\n{ok} uploaded, {fail} failed.')
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
