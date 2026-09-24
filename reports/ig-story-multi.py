#!/usr/bin/env python3
"""Multi-card Instagram story frames: 2-4 cards per 1080x1920 post, each with its price.

Craig's brief, 2026-09-16: "instagram story tonight with the new comp prices of the
cards we just updated ... 2-4 cards per post with the price."

Single-card frames (ig-render.py) make the card the hero. A multi-card frame is a
price list, so the job is different: every card must be legible at story size and
every price must be unmistakably attached to its own card. That means a strict grid,
one price directly under each image, and nothing else competing.

Cards are grouped by price tier so a $55 auto never sits beside a $5 common — a
mixed frame makes the dear card look cheap and the cheap card look overpriced.

    python3 reports/ig-story-multi.py                 # today's comped cards
    python3 reports/ig-story-multi.py --per 3         # 3 per frame instead of 4
    python3 reports/ig-story-multi.py --rows 234,40   # explicit tracker row numbers
"""
import argparse, csv, json, os, re, sys, urllib.parse, urllib.request
from datetime import date
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, '..', 'public', 'images', 'logo.png')
TRACKER = os.path.join(HERE, 'COMP-TRACKER.csv')
SHOP_ORIGIN = 'https://duxburytradingpost.myshopify.com'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DTP-IG/1.0'

W, H  = 1080, 1920
GREEN = (10, 40, 20)
CREAM = (247, 244, 235)
SAGE  = (185, 205, 192)

GRID_X0, GRID_X1 = 60, 1020
GRID_Y0, GRID_Y1 = 300, 1630
CTA_TOP = H - 200

FONT_DIRS = ['/System/Library/Fonts/Supplemental', '/System/Library/Fonts', '/Library/Fonts']
FACES = {'bold':   ['Futura.ttc', 'HelveticaNeue.ttc', 'Helvetica.ttc', 'Arial Bold.ttf'],
         'normal': ['HelveticaNeue.ttc', 'Helvetica.ttc', 'Arial.ttf']}


def font(kind, size):
    for name in FACES[kind]:
        for d in FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size, index=1 if (kind == 'bold' and p.endswith('.ttc')) else 0)
                except Exception:
                    try:
                        return ImageFont.truetype(p, size)
                    except Exception:
                        continue
    return ImageFont.load_default(size)


def centred_in(d, x0, x1, y, text, fnt, fill):
    w = d.textbbox((0, 0), text, font=fnt)[2]
    d.text((x0 + (x1 - x0 - w) // 2, y), text, font=fnt, fill=fill)


def wrap(d, text, fnt, max_w, max_lines=None):
    """Wrap to max_w. With max_lines=None nothing is dropped or ellipsised."""
    words, lines, cur = text.split(), [], ''
    for word in words:
        trial = (cur + ' ' + word).strip()
        if d.textbbox((0, 0), trial, font=fnt)[2] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
            if max_lines and len(lines) == max_lines:
                break
    if cur and (max_lines is None or len(lines) < max_lines):
        lines.append(cur)
    if max_lines and len(lines) == max_lines and len(' '.join(lines)) < len(text):
        lines[-1] = lines[-1].rstrip('.,') + '...'
    return lines


def fit_title(d, text, max_w, max_h, base_size, floor_size=17):
    """Every word of the title, always.

    Craig, 2026-09-16: "make sure the entire title of each card is displayed."
    Truncating to two lines with an ellipsis hid exactly the part that identifies
    the card — "Rookies Citrine /25 Tar Heels..." dropped the PSA grade. So the
    type shrinks to fit the space instead of the text being cut to fit the type.
    Returns (font, lines, line_height)."""
    size = base_size
    while size >= floor_size:
        f = font('normal', size)
        lh = size + 7
        lines = wrap(d, text, f, max_w, None)
        if len(lines) * lh <= max_h and all(
                d.textbbox((0, 0), ln, font=f)[2] <= max_w for ln in lines):
            return f, lines, lh
        size -= 1
    f = font('normal', floor_size)
    return f, wrap(d, text, f, max_w, None), floor_size + 7


def short_title(t):
    """Strip the year and brand down to what a buyer scans for: player, card
    number, parallel. A story caption has no room for '2024 Panini Donruss Optic'."""
    t = re.sub(r'^(19|20)\d\d(-\d\d)?\s+', '', t)
    t = re.sub(r'^(Panini|Topps|Upper Deck|Leaf|Bowman)\s+', '', t)
    t = re.sub(r'\s+(RC|Rookie)\b', '', t)
    return t.strip()


def _get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def _toks(t):
    return set(w for w in re.sub(r'[^a-z0-9/#]+', ' ', t.lower()).split()
               if w not in {'rc', 'the', 'a', 'panini', 'topps'})


def image_url(title):
    """Front image for THIS card, or None.

    The storefront search always returns its nearest hit, so a card it cannot
    find comes back as a different card's photo rather than as an error. That
    happened on 2026-09-16: the Keon Coleman Pink Velocity auto is tagged
    Personal with qty 0, so suggest.json skipped it and offered the Red /125
    PSA 10 instead — a completely different card, silently. Nothing downstream
    could have caught it.

    So the hit is verified against the requested title before its image is used.
    A wrong price is embarrassing; a wrong photo is a dispute."""
    q = urllib.parse.urlencode({'q': title, 'resources[type]': 'product', 'resources[limit]': 3})
    try:
        d = _get(f'{SHOP_ORIGIN}/search/suggest.json?{q}')
        hits = d['resources']['results']['products']
    except Exception:
        return None
    want = _toks(title)
    for hit in hits:
        got = _toks(hit.get('title', ''))
        if len(want & got) / max(1, len(want | got)) >= 0.75:
            img = hit.get('featured_image')
            return img.get('url') if isinstance(img, dict) else (img or None)
    return None


def fetch(title, dest):
    if os.path.exists(dest):
        return dest
    src = image_url(title)
    if not src:
        return None
    req = urllib.request.Request(src, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, 'wb') as fh:
        fh.write(r.read())
    return dest


def paste_card(bg, path, box, cx, cy_top):
    """Fit the card in `box`, centre it horizontally on cx, drop a soft shadow.
    Returns the height actually used."""
    c = Image.open(path).convert('RGB')
    c.thumbnail(box, Image.LANCZOS)
    x = cx - c.width // 2
    sh = Image.new('RGBA', (c.width + 60, c.height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((30, 30, c.width + 30, c.height + 30), fill=(0, 0, 0, 140))
    sh = sh.filter(ImageFilter.GaussianBlur(18))
    bg.paste(sh, (x - 30, cy_top - 22), sh)
    bg.paste(c, (x, cy_top))
    return c.height


def render(cards, out_path, heading=None):
    """cards: list of (image_path, price, title, qty). 2-4 of them."""
    n = len(cards)
    bg = Image.new('RGB', (W, H), GREEN)

    bleed = Image.open(cards[0][0]).convert('RGB')
    bleed = bleed.resize((W, int(W * bleed.height / bleed.width)))
    bleed = bleed.filter(ImageFilter.GaussianBlur(70))
    bg.paste(bleed, (0, max(0, (H - bleed.height) // 2)))
    bg = Image.blend(bg, Image.new('RGB', (W, H), GREEN), 0.86)
    d = ImageDraw.Draw(bg)

    if os.path.exists(LOGO):
        lg = Image.open(LOGO).convert('RGBA')
        lg = lg.resize((300, int(300 * lg.height / lg.width)))
        tint = Image.new('RGBA', lg.size, CREAM + (255,))
        tint.putalpha(lg.getchannel('A'))
        bg.paste(tint, ((W - tint.width) // 2, 86), tint)
    else:
        centred_in(d, 0, W, 120, 'DUXBURY TRADING POST', font('bold', 34), SAGE)

    rows = 1 if n <= 2 else 2
    cols = 2

    # A two-up frame is width-limited, not height-limited: the cards can only be
    # as wide as half the frame, so a portrait card tops out around 640px tall and
    # the default grid left ~240px of dead green above and below it. Two-up gets
    # its own tighter band and wider gutters-in so the pair fills the frame.
    if n == 2:
        gx0, gx1, gy0, gy1 = 45, 1035, 330, 1570
        card_box, pf, tlines = (462, 800), font('bold', 96), 33
    else:
        gx0, gx1, gy0, gy1 = GRID_X0, GRID_X1, GRID_Y0, GRID_Y1
        card_box, pf, tlines = (400, 420), font('bold', 62), 25

    cell_w = (gx1 - gx0) // cols
    cell_h = (gy1 - gy0) // rows

    # Cards are not all the same shape — a landscape card thumbnails much shorter
    # than a portrait one. Centring each cell's content independently then leaves
    # the prices in a row sitting at different heights, which reads as sloppy
    # rather than deliberate (the Stroud Fireworks frame, 2026-09-16). So the
    # card images in a row share ONE bottom baseline and the prices below them
    # share one top edge. Short cards simply carry more air above them.
    heights = []
    for path, _, _, _ in cards:
        probe = Image.open(path)
        probe.thumbnail(card_box, Image.LANCZOS)
        heights.append(probe.height)

    for i, (path, price, title, qty) in enumerate(cards):
        r, c = divmod(i, cols)
        row_h = max(heights[r * cols:(r + 1) * cols] or [0])

        # a lone card on the last row is centred rather than left-hung
        in_row = min(cols, n - r * cols)
        if in_row < cols:
            x0 = gx0 + (gx1 - gx0 - in_row * cell_w) // 2 + c * cell_w
        else:
            x0 = gx0 + c * cell_w
        y0 = gy0 + r * cell_h
        cx = x0 + cell_w // 2

        ptxt = f'${price:,.0f}'
        ph = d.textbbox((0, 0), ptxt, font=pf)[3]
        title_h = cell_h - row_h - 18 - ph - 10 - (36 if qty > 1 else 0) - 12
        tf, lines, line_h = fit_title(d, title, cell_w - 26, title_h, tlines)
        lh = line_h * len(lines)
        # two copies of one card get one tile with the count on it, never two tiles
        qf = font('bold', max(20, tf.size - 2)) if qty > 1 else None
        qh = (qf.size + 8) if qf else 0

        block = row_h + 18 + ph + 10 + lh + qh
        top = y0 + max(0, (cell_h - block) // 2)
        baseline = top + row_h                      # shared by every card in the row

        used = paste_card(bg, path, card_box, cx, baseline - heights[i])
        y = baseline + 18
        centred_in(d, x0, x0 + cell_w, y, ptxt, pf, CREAM)
        y += ph + 10
        for line in lines:
            centred_in(d, x0, x0 + cell_w, y, line, tf, SAGE)
            y += line_h
        if qf:
            centred_in(d, x0, x0 + cell_w, y + 4, f'{qty} AVAILABLE', qf, CREAM)

    cta, txt = font('bold', 40), 'DM TO CLAIM'
    tw = d.textbbox((0, 0), txt, font=cta)[2]
    bx0 = (W - tw) // 2 - 46
    d.rounded_rectangle((bx0, CTA_TOP, bx0 + tw + 92, CTA_TOP + 92), radius=46, fill=CREAM)
    d.text(((W - tw) // 2, CTA_TOP + 24), txt, font=cta, fill=GREEN)

    bg.save(out_path, 'JPEG', quality=92)
    return out_path


TODAY = ['234', '40', '42', '41', '43', '46', '45', '44',
         '47', '49', '48', '50', '51', '52', '235', '236']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--per', type=int, default=4, choices=(2, 3, 4))
    ap.add_argument('--mix', action='store_true',
                    help='2 per frame for the dearest cards, 3 in the middle, 4 for the tail')
    ap.add_argument('--rows', default='')
    ap.add_argument('--out', default='')
    a = ap.parse_args()

    want = [s.strip() for s in a.rows.split(',') if s.strip()] or TODAY
    by_n = {r['n']: r for r in csv.DictReader(open(TRACKER))}
    picks = []
    for n in want:
        r = by_n.get(n)
        if not r:
            print(f'[no tracker row {n}]', file=sys.stderr)
            continue
        try:
            price = float(str(r['your_comp']).replace('$', '').replace(',', ''))
        except Exception:
            print(f'[row {n} has no comp — skipped]', file=sys.stderr)
            continue
        try:
            qty = int(str(r.get('qty') or 1).strip() or 1)
        except Exception:
            qty = 1
        picks.append((price, r['title'], qty))

    # dearest first, so the tiers group themselves
    picks.sort(key=lambda p: -p[0])

    out = a.out or os.path.join(HERE, f'ig-story-{date.today()}')
    raw = os.path.join(out, '_raw')
    os.makedirs(raw, exist_ok=True)

    staged, failed = [], 0
    for price, title, qty in picks:
        slug = re.sub(r'[^A-Za-z0-9]+', '-', title)[:60].strip('-')
        dest = os.path.join(raw, f'{slug}.jpg')
        try:
            got = fetch(title, dest)
        except Exception as e:
            got = None
            print(f'[image failed: {title[:44]} — {e}]', file=sys.stderr)
        if got:
            staged.append((got, price, title, qty))
        else:
            failed += 1
            print(f'[no image: {title[:52]}]', file=sys.stderr)

    if a.mix:
        # A $750 card and a $55 card do not deserve the same square footage. The
        # top of the book gets two per frame so each card is nearly full-bleed;
        # the middle gets three; the tail gets four. Same total cards, better
        # attention where the money is.
        frames, i = [], 0
        for count, take in ((2, 6), (3, 12), (4, 10 ** 6)):
            end = min(len(staged), i + take)
            while i < end:
                frames.append(staged[i:i + count])
                i += count
            if i >= len(staged):
                break
    else:
        frames = [staged[i:i + a.per] for i in range(0, len(staged), a.per)]
    # never leave a single card stranded on the last frame
    if len(frames) > 1 and len(frames[-1]) == 1:
        frames[-2].append(frames[-1].pop())
        frames.pop()

    made = []
    for i, group in enumerate(frames, 1):
        lo, hi = min(g[1] for g in group), max(g[1] for g in group)
        heading = f'${lo:,.0f}' if lo == hi else f'${lo:,.0f} - ${hi:,.0f}'
        p = os.path.join(out, f'STORY-{i:02d}__{len(group)}-cards.jpg')
        render(group, p, heading)
        made.append((p, group))

    with open(os.path.join(out, 'CAPTIONS.txt'), 'w') as fh:
        fh.write(f'DTP INSTAGRAM STORY — {date.today()}\n')
        fh.write('Prices are confirmed market comps. DM to claim.\n\n')
        for p, group in made:
            fh.write(os.path.basename(p) + '\n')
            for _, price, title, qty in group:
                fh.write(f'   ${price:,.0f}   {title}' + (f'   (x{qty})' if qty > 1 else '') + '\n')
            fh.write('\n')

    print(f'{len(made)} story frames, {len(staged)} cards -> {out}'
          + (f'  ({failed} image{"s" if failed != 1 else ""} missing)' if failed else ''))
    for p, group in made:
        print(f'  {os.path.basename(p)}  ' + ', '.join(f'${pr:,.0f}' for _, pr, _, _ in group))
    return 0


if __name__ == '__main__':
    sys.exit(main())
