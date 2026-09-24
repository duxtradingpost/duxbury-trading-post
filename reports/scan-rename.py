#!/usr/bin/env python3
"""Pairs raw fi-8170 duplex scans into card-001-front.jpg / card-001-back.jpg.

    python3 reports/scan-rename.py                      # dry run, shows what it would do
    python3 reports/scan-rename.py --stack 50 --apply    # rename, and check all 50 got both sides
    python3 reports/scan-rename.py --single --apply      # treat the whole folder as one batch

Why this exists
---------------
Image Capture names duplex scans `card.jpeg`, `card 1.jpeg`, `card 2.jpeg` ...
The first file has no number at all, so the numbering runs one behind what you
would expect: `card.jpeg` + `card 1.jpeg` is the FIRST card, `card 2.jpeg` +
`card 3.jpeg` the second. Every odd-numbered file is a back.

Worse, those names do not sort into feed order. In ASCII a space sorts before a
dot, so `card 1.jpeg` sorts BEFORE `card.jpeg` — the back of card one lands
first — and Finder's own numeric sort puts them somewhere else again. Sorting a
scan run by name and trusting it will silently reverse pairs.

So this ignores names entirely and orders by **file creation time**, which
always matches the order the cards went through the feeder. Checked on the
fi-8170: birth times carry sub-second precision (.198 vs .625 within the same
second), so consecutive sides of one card never tie.

That ordering matters downstream. Shopify product images are front-then-back and
public/js/inventory.js reads the SECOND image as the card back, so a reversed
pair puts a card back on the listing thumbnail.

What it refuses to do
---------------------
A misfeed costs you one side, and the real damage is not that card — it is the
forty cards behind it that shift by one and get silently mispaired. Guards:

  * an odd file count in a batch means a side is missing, and the batch is
    refused rather than renamed into garbage
  * --stack N says how many cards you fed; the count must match exactly
  * anything not roughly card-shaped is flagged (a double-feed scans as one tall
    image, a wrong Size setting scans as a page with a card in the corner)

None of that catches TWO missing sides in one batch, which is the reason to type
--stack. If a batch is refused, open the folder sorted by Date Created, find the
card missing a side, rescan it on its own and move it aside.
"""
import argparse, os, re, shutil, sys
from datetime import datetime
from pathlib import Path

SCAN_DIR = Path.home() / "Pictures" / "Card Scans"
EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
DONE = re.compile(r"^card-\d{3,}-(front|back)\.", re.I)

# a 2.5x3.5in card at 600dpi, with room for auto-crop slop and other resolutions
CARD_RATIO = 3.5 / 2.5
RATIO_TOL = 0.12


def dimensions(path):
    """(width_px, height_px, dpi) -- dpi is None when the file does not say."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            dpi = im.info.get("dpi")
            d = float(dpi[0]) if dpi and dpi[0] else None
            return im.size[0], im.size[1], d
    except Exception:
        return None


def shape_note(path):
    """Flag anything that is not a single bare card. None when it looks right."""
    size = dimensions(path)
    if not size:
        return "unreadable"
    w, h, dpi = size
    if w == 0 or h == 0:
        return "zero-sized"
    ratio = h / w if h >= w else w / h

    # PHYSICAL SIZE CHECK -- catches a card scanned INSIDE its holder.
    # Added 2026-09-21 after a 10-card feed came back entirely as 3.00x4.00in
    # images: the cards were still in TOPLOADERS. The ratio guard did NOT catch
    # it -- a toploader is 3x4, ratio 1.33, which sits inside the +/-0.12 band
    # around 1.40 -- so all but three files PASSED, and only a count mismatch
    # stopped nine toploader scans being uploaded. Ratio alone cannot tell a
    # small rectangle from a big one; measure the inches.
    # A bare card is 2.5 x 3.5in. A toploader is 3 x 4in, a penny sleeve ~2.75
    # x 3.75in, a semi-rigid bigger again. See dtp-ricoh-fi8170-scanner: none of
    # these should go through the ADF anyway -- the fi-8170 tops out at 1.4mm.
    # Craig scans cards INSIDE TOPLOADERS by preference (2026-09-21) - taking
    # them in and out is slow and risks the card. So a holder is NOT an error.
    # Two acceptable size classes, measured off real batches:
    #
    #   bare card  2.50-2.52 x 3.49-3.52in
    #   toploader  2.98-3.12 x 3.77-4.03in   (a 3x4 holder; the top lip is
    #                                          sometimes cropped, and a 3.77in
    #                                          scan still shows the whole card -
    #                                          verified on a KeAndre
    #                                          Lambert-Smith Optic RR)
    #
    # What must still be caught is a DOUBLE FEED (two items scanned as one tall
    # image - 2.99x4.87 and 3.12x5.15 were seen in one batch) and a crop that
    # cuts INTO the card (the clipped Kittle back, 2.51x3.00).
    if dpi and dpi > 0:
        short_in, long_in = min(w, h) / dpi, max(w, h) / dpi
        card = 2.30 <= short_in <= 2.70 and 3.25 <= long_in <= 3.75
        holder = 2.70 <= short_in <= 3.30 and 3.60 <= long_in <= 4.30
        if not (card or holder):
            if long_in > 4.30 or short_in > 3.30:
                why = "too big - DOUBLE FEED? two items scanned as one"
            elif long_in < 3.25:
                why = "too short - the crop has cut INTO the card"
            else:
                why = "not a card or a toploader"
            return "%.2fx%.2fin -- %s" % (short_in, long_in, why)
        return None

    # No DPI in the file, so fall back to the shape-only check.
    if abs(ratio - CARD_RATIO) > RATIO_TOL:
        return "not card-shaped (%dx%d, ratio %.2f vs %.2f)" % (w, h, ratio, CARD_RATIO)
    return None


def collect(folder):
    out = []
    for p in sorted(folder.iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in EXTS or DONE.match(p.name):
            continue
        st = p.stat()
        born = getattr(st, "st_birthtime", st.st_mtime)
        out.append((born, p))
    out.sort(key=lambda t: t[0])
    return out


def split_batches(files, gap, single):
    if single or not files:
        return [files] if files else []
    batches, cur = [], [files[0]]
    for prev, curf in zip(files, files[1:]):
        if curf[0] - prev[0] > gap:
            batches.append(cur)
            cur = []
        cur.append(curf)
    batches.append(cur)
    return batches


def main():
    ap = argparse.ArgumentParser(description="Pair and rename fi-8170 duplex card scans.")
    ap.add_argument("folder", nargs="?", default=str(SCAN_DIR), help="scan folder (default: ~/Pictures/Card Scans)")
    ap.add_argument("--stack", type=int, help="cards you fed per stack; batch count must match exactly")
    ap.add_argument("--gap", type=float, default=120.0, help="seconds between files that starts a new batch (default 120)")
    ap.add_argument("--single", action="store_true", help="treat the whole folder as one batch")
    ap.add_argument("--back-first", action="store_true", help="stack was loaded face up")
    ap.add_argument("--quarantine", action="store_true",
                    help="move bad pairs to _rescan-needed/ and process the rest, "
                         "instead of refusing the whole batch")
    ap.add_argument("--apply", action="store_true", help="actually rename (default is a dry run)")
    args = ap.parse_args()

    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        sys.exit("No such folder: %s" % folder)

    files = collect(folder)
    if not files:
        sys.exit("No unrenamed scans in %s" % folder)

    batches = split_batches(files, args.gap, args.single)
    print("%d file(s) in %s -> %d batch(es)\n" % (len(files), folder, len(batches)))

    sides = ("back", "front") if args.back_first else ("front", "back")
    refused = 0

    for i, batch in enumerate(batches, 1):
        stamp = datetime.fromtimestamp(batch[0][0])

        # --quarantine: lift the bad pair out instead of refusing everything.
        # One clipped scan used to cost a rescan of the whole stack -- that
        # happened twice on 2026-09-21 (a clipped card back in a 12-card feed,
        # and three oversized files in a 10-card feed) and both times the fix
        # was done by hand: move the bad pair aside, run the rest, rescan the
        # one card. This does that automatically.
        #
        # Only safe when the file count is EVEN. An odd count means a SIDE is
        # missing, so every pair behind it has shifted by one and no amount of
        # removing files re-aligns them -- that still refuses.
        quarantined = []
        if args.quarantine and len(batch) % 2 == 0:
            bad = set()
            for n, (_, p) in enumerate(batch):
                if shape_note(p):
                    bad.add(n)
                    bad.add(n ^ 1)          # take its front/back partner too
            if bad and len(bad) < len(batch):
                quarantined = [b for n, b in enumerate(batch) if n in bad]
                batch = [b for n, b in enumerate(batch) if n not in bad]

        cards = len(batch) // 2
        fed = cards + len(quarantined) // 2
        label = "batch %d  %s  %d file(s), %d card(s)" % (i, stamp.strftime("%Y-%m-%d %H:%M"), len(batch), cards)

        problems = []
        if len(batch) % 2:
            problems.append("ODD file count — a side is missing, pairs after it would shift")
        if args.stack and fed != args.stack:
            problems.append("expected %d cards, found %d — %d side(s) unaccounted for"
                            % (args.stack, fed, abs(args.stack * 2 - (len(batch) + len(quarantined)))))
        for _, p in batch:
            note = shape_note(p)
            if note:
                problems.append("%s: %s" % (p.name, note))

        if problems:
            print("REFUSED  " + label)
            for pr in problems:
                print("    ! " + pr)
            if quarantined:
                print("    (%d file(s) already set aside; the problem above is separate)"
                      % len(quarantined))
            if not args.quarantine:
                print("    Re-run with --quarantine to set the bad pair aside and keep the rest.")
            print("    Sort the folder by Date Created, find the card, rescan it separately.\n")
            refused += 1
            continue

        if quarantined:
            qdir = folder / "_rescan-needed"
            print("QUARANTINE  %d file(s) (%d card(s)) set aside -> %s/"
                  % (len(quarantined), len(quarantined) // 2, qdir.name))
            for _, p in quarantined:
                print("             %-18s %s" % (p.name, shape_note(p) or "pair partner"))
            if args.apply:
                qdir.mkdir(parents=True, exist_ok=True)
                for _, p in quarantined:
                    shutil.move(str(p), str(qdir / p.name))
            print()

        # Batch numbers restart at 1 every run, so a second run on the same day
        # used to collide with the first and get refused. Skip forward to the
        # next free number instead -- refusing here would be a false alarm, and
        # the whole point of the guards is that a REFUSED line means real trouble.
        n = i
        while True:
            dest = folder / ("%s-batch%d" % (stamp.strftime("%Y-%m-%d"), n))
            if not (dest.exists() and any(dest.iterdir())):
                break
            n += 1
        if n != i:
            print("    (batch%d taken -- using batch%d)" % (i, n))

        print("OK       %s  ->  %s/" % (label, dest.name))
        moves = []
        for n in range(cards):
            for k in (0, 1):
                src = batch[n * 2 + k][1]
                moves.append((src, dest / ("card-%03d-%s.jpg" % (n + 1, sides[k]))))
        preview = moves if len(moves) <= 6 else moves[:3] + [None] + moves[-3:]
        for mv in preview:
            if mv is None:
                print("             ... %d more ..." % (len(moves) - 6))
            else:
                print("             %-18s -> %s" % (mv[0].name, mv[1].name))

        if args.apply:
            dest.mkdir(parents=True, exist_ok=True)
            for src, dst in moves:
                shutil.move(str(src), str(dst))
            print("             moved %d file(s)" % len(moves))
        print()

    if not args.apply and refused < len(batches):
        print("Dry run. Add --apply to rename.")
    if refused:
        sys.exit(1)


if __name__ == "__main__":
    main()
