#!/usr/bin/env python3
"""Turn a staged card image into a 1080x1920 Instagram story frame.

Craig's brief: "story should be a pic of the card and a price point." So the card
is the hero and the price is the only other thing that competes for attention.
Everything else — wordmark, call to action — stays quiet.

Brand colours are lifted from the storefront CSS so the frames match the site:
deep green #0A2814, cream #F7F4EB, sage #B9CDC0.

    python3 ig-render.py            # render everything in ig-cards/_raw
"""
import glob, json, os, re, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE  = os.path.dirname(os.path.abspath(__file__))
CARDS = os.path.join(HERE, 'ig-cards')
RAW   = os.path.join(CARDS, '_raw')
LOGO  = os.path.join(HERE, '..', 'public', 'images', 'logo.png')

W, H       = 1080, 1920
GREEN      = (10, 40, 20)
CREAM      = (247, 244, 235)
SAGE       = (185, 205, 192)
CARD_BOX   = (820, 1030)      # the card is fitted inside this, centred
CARD_TOP   = 290
CTA_TOP    = H - 200          # everything below the card is laid out from here UP,
                              # so a long title can never collide with the button

FONT_DIRS = ['/System/Library/Fonts/Supplemental', '/System/Library/Fonts', '/Library/Fonts']
FACES = {'bold':   ['Futura.ttc', 'HelveticaNeue.ttc', 'Helvetica.ttc', 'Arial Bold.ttf'],
         'normal': ['HelveticaNeue.ttc', 'Helvetica.ttc', 'Arial.ttf']}


def font(kind, size):
    for name in FACES[kind]:
        for d in FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.exists(p):
                try:
                    # .ttc files carry several faces; index 1 is usually the bold-ish one
                    return ImageFont.truetype(p, size, index=1 if (kind == 'bold' and p.endswith('.ttc')) else 0)
                except Exception:
                    try:
                        return ImageFont.truetype(p, size)
                    except Exception:
                        continue
    return ImageFont.load_default(size)


def centred(draw, y, text, fnt, fill):
    w = draw.textbbox((0, 0), text, font=fnt)[2]
    draw.text(((W - w) // 2, y), text, font=fnt, fill=fill)
    return w


def wrap(draw, text, fnt, max_w, max_lines=2):
    words, lines, cur = text.split(), [], ''
    for word in words:
        trial = (cur + ' ' + word).strip()
        if draw.textbbox((0, 0), trial, font=fnt)[2] <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and len(' '.join(lines)) < len(text):
        lines[-1] = lines[-1].rstrip('.,') + '...'
    return lines


def render(card_path, price, title, out_path, qty=1):
    bg = Image.new('RGB', (W, H), GREEN)

    # A blurred, darkened copy of the card bleeding behind it — gives the frame
    # depth without needing a designed background per card.
    card = Image.open(card_path).convert('RGB')
    bleed = card.copy().resize((W, int(W * card.height / card.width)))
    bleed = bleed.filter(ImageFilter.GaussianBlur(60))
    bg.paste(bleed, (0, max(0, (H - bleed.height) // 2)))
    bg = Image.blend(bg, Image.new('RGB', (W, H), GREEN), 0.80)

    d = ImageDraw.Draw(bg)

    # wordmark — the logo art is the same deep green as the background, so it is
    # recoloured to cream through its own alpha or it simply disappears.
    if os.path.exists(LOGO):
        lg = Image.open(LOGO).convert('RGBA')
        lg = lg.resize((330, int(330 * lg.height / lg.width)))
        tint = Image.new('RGBA', lg.size, CREAM + (255,))
        tint.putalpha(lg.getchannel('A'))
        bg.paste(tint, ((W - tint.width) // 2, 96), tint)
    else:
        centred(d, 130, 'DUXBURY TRADING POST', font('bold', 34), SAGE)

    # the card, fitted and centred, with a soft drop shadow
    c = card.copy()
    c.thumbnail(CARD_BOX, Image.LANCZOS)
    # Centre the card in the reserved box, do NOT top-align it. A LANDSCAPE card
    # thumbnails to about 820x590 in an 820x1030 box, so top-aligning left ~440px
    # of dead green between the card and the price — the Josh Allen Top 100 frame
    # on 11 Sept. Portrait cards fill the box, so this changes nothing for them.
    cx = (W - c.width) // 2
    cy = CARD_TOP + max(0, (CARD_BOX[1] - c.height) // 2)
    shadow = Image.new('RGBA', (c.width + 80, c.height + 80), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((40, 40, c.width + 40, c.height + 40), fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    bg.paste(shadow, (cx - 40, cy - 30), shadow)
    bg.paste(c, (cx, cy))

    # Everything under the card is placed from the button upwards, so a two-line
    # title can never run under the pill the way it did on the first pass.
    cta = font('bold', 40)
    txt = 'DM TO CLAIM'
    # Two copies of one card get ONE frame with the count on it, not two frames.
    # Same price either way — it is comp-derived, so the copies cannot differ.
    if qty > 1:
        qf = font('bold', 32)
        centred(d, CTA_TOP + 104, f'{qty} AVAILABLE', qf, SAGE)
    tw = d.textbbox((0, 0), txt, font=cta)[2]
    bx0 = (W - tw) // 2 - 46
    d.rounded_rectangle((bx0, CTA_TOP, bx0 + tw + 92, CTA_TOP + 92), radius=46, fill=CREAM)
    d.text(((W - tw) // 2, CTA_TOP + 24), txt, font=cta, fill=GREEN)

    tf = font('normal', 36)
    lines = wrap(d, title, tf, W - 190, 2)
    ty = CTA_TOP - 44 - (len(lines) * 46)
    for line in lines:
        centred(d, ty, line, tf, SAGE)
        ty += 46

    # price — the second thing the eye lands on, and the only other loud element
    pf = font('bold', 158)
    ph = d.textbbox((0, 0), f'${price:,.0f}', font=pf)[3]
    centred(d, CTA_TOP - 44 - (len(lines) * 46) - ph - 46, f'${price:,.0f}', pf, CREAM)

    bg.save(out_path, 'JPEG', quality=92)
    return out_path


def main():
    try:
        wk = json.load(open(os.path.join(HERE, 'ig-this-week.json')))
    except Exception:
        print('no ig-this-week.json — run ig-wednesday.py first', file=sys.stderr)
        return 1
    by_slug = {}
    for p in wk['picks']:
        by_slug[re.sub(r'[^A-Za-z0-9]+', '-', p['title'])[:56].strip('-')] = p
    made = 0
    for src in sorted(glob.glob(os.path.join(RAW, '*.jpg'))):
        base = os.path.basename(src)
        m = re.match(r'(\d+)__POST-([\d.]+)__(.+)\.jpg$', base)
        if not m:
            continue
        idx, price, slug = m.group(1), float(m.group(2)), m.group(3)
        pick = by_slug.get(slug)
        title = pick['title'] if pick else slug.replace('-', ' ')
        out = os.path.join(CARDS, f'{idx}__POST-{price:.0f}.jpg')
        render(src, price, title, out, qty=(pick or {}).get('qty', 1))
        made += 1
    print(f'{made} story frames -> {CARDS}')
    return made


if __name__ == '__main__':
    sys.exit(main())
