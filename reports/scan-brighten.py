#!/usr/bin/env python3
"""Lift the exposure on fi-8170 card scans before they go to Heystack.

    python3 reports/scan-brighten.py "<batch folder>"            # dry run
    python3 reports/scan-brighten.py "<batch folder>" --apply     # rewrite in place

Why this exists
---------------
Craig, 2026-09-21: "the cards scanned by the ricoh scanner are dark". Measured
across a batch, they are: mean luminance 48-74 out of 255, p5 at 1 (blacks
crushed) and p95 only 130-203, so the image never reaches white. The whole
tonal range sits compressed at the bottom. Scanning through a TOPLOADER makes it
worse - the plastic costs light and adds a grey veil.

WHAT THIS DOES AND DOES NOT DO. It is a levels stretch (PIL autocontrast): the
darkest pixels are mapped to black and the lightest to white, and everything
between is scaled to match. It restores the range the scanner failed to capture.
It is NOT a beautifier - it does not touch saturation, sharpness or colour
balance, and it cannot hide a crease, a soft corner or edge wear. That matters:
these are SALES photos, and a picture that flatters a card is a misrepresentation
Craig would wear on the return.

MID-TONE LIFT (2026-09-23). After the stretch, a gamma of 0.8 lifts the
mid-tones. Tested on a 10-card foil Pokemon batch against 0.7 and no lift:
the stretch alone left foil art grey, 0.7 washed the foil flat, 0.8 matched
the card in hand. Black and white points are unchanged, so it does not hide
whitening, scratches or dings.

ONE PASS PER FILE. A brightened scan is tagged with a JPEG comment and never
touched again. The gamma makes this necessary: a dark foil can still sit under
DARK_MEAN after one pass, and a second pass would stack the lift. Files
already bright enough are skipped outright.

Tone adjustment in Image Capture was tested the same day (Normal vs lighter,
same 10 cards) and changed nothing - the correction has to happen here.

DPI IS PRESERVED DELIBERATELY. scan-rename.py decides toploader-vs-bare-card from
the JPEG's dpi tag; re-saving without it would strip that and every scan would
start failing the shape check. See dtp-ricoh-fi8170-scanner.
"""
import argparse, os, sys
from PIL import Image, ImageOps, ImageStat

# Below this mean luminance a scan is underexposed enough to be worth lifting.
# Good bare-card scans measured 120-150; the dark toploader batch was 48-74.
DARK_MEAN = 110.0
CUTOFF = 0.5        # percent clipped at each end - conservative on purpose
GAMMA = 0.8         # mid-tone lift after the stretch; <1 brightens
QUALITY = 92
MARK = b'dtp-brightened'
_LUT = [round(255 * (i / 255) ** GAMMA) for i in range(256)] * 3


def measure(path):
    with Image.open(path) as im:
        g = im.convert('L')
        return ImageStat.Stat(g).mean[0]


def brighten(path, apply):
    with Image.open(path) as im:
        dpi = im.info.get('dpi', (600, 600))
        before = ImageStat.Stat(im.convert('L')).mean[0]
        if before >= DARK_MEAN or MARK in (im.info.get('comment') or b''):
            return before, before, False
        out = ImageOps.autocontrast(im.convert('RGB'), cutoff=(CUTOFF, CUTOFF)).point(_LUT)
        after = ImageStat.Stat(out.convert('L')).mean[0]
        if apply:
            # dpi carried through or scan-rename can no longer tell a card from
            # a toploader.
            out.save(path, 'JPEG', quality=QUALITY, dpi=dpi, subsampling=0, comment=MARK)
        return before, after, True


def main():
    ap = argparse.ArgumentParser(description='Brighten dark card scans in place.')
    ap.add_argument('folder')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    folder = os.path.expanduser(a.folder)
    if not os.path.isdir(folder):
        sys.exit('No such folder: ' + folder)
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(('.jpg', '.jpeg')))
    if not files:
        sys.exit('No scans in ' + folder)

    done = skipped = 0
    for f in files:
        b, aft, changed = brighten(os.path.join(folder, f), a.apply)
        if changed:
            done += 1
            print(f'  {f:22} {b:5.1f} -> {aft:5.1f}')
        else:
            skipped += 1
    print(f'\n{done} brightened, {skipped} already bright enough or already done'
          f'{"" if a.apply else "  (DRY RUN - add --apply)"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
