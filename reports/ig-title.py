#!/usr/bin/env python3
"""Opening title frame for the Instagram story sale.

    python3 reports/ig-title.py                # -> ig-cards/00__TITLE.jpg

Same 1080x1920 canvas and brand palette as the card frames so it reads as the
first slide of one set, not a different thing bolted on. Reuses ig_render's font
resolver and logo tinting rather than re-deriving them.
"""
import os, sys
from PIL import Image, ImageDraw

import ig_render as R

OUT = os.path.join(R.CARDS, '00__TITLE.jpg')


def main(count=None, out=OUT):
    bg = Image.new('RGB', (R.W, R.H), R.GREEN)
    d = ImageDraw.Draw(bg)

    # A faint off-centre glow so a flat green field does not look like a
    # rendering failure on a phone screen.
    glow = Image.new('L', (R.W, R.H), 0)
    ImageDraw.Draw(glow).ellipse((-260, 380, R.W + 260, R.H - 380), fill=54)
    bg.paste(Image.new('RGB', (R.W, R.H), (22, 66, 38)), (0, 0), glow.filter(
        __import__('PIL.ImageFilter', fromlist=['ImageFilter']).GaussianBlur(190)))
    d = ImageDraw.Draw(bg)

    if os.path.exists(R.LOGO):
        lg = Image.open(R.LOGO).convert('RGBA')
        lg = lg.resize((430, int(430 * lg.height / lg.width)))
        tint = Image.new('RGBA', lg.size, R.CREAM + (255,))
        tint.putalpha(lg.getchannel('A'))
        bg.paste(tint, ((R.W - tint.width) // 2, 300), tint)
    else:
        R.centred(d, 340, 'DUXBURY TRADING POST', R.font('bold', 40), R.SAGE)

    # STORY SALE, stacked — one word per line gets the type far bigger than a
    # single line can, and this is the slide people see for one second.
    R.centred(d, 780,  'STORY',  R.font('bold', 210), R.CREAM)
    R.centred(d, 1000, 'SALE',   R.font('bold', 210), R.CREAM)

    rule_y = 1290
    d.rounded_rectangle((R.W // 2 - 150, rule_y, R.W // 2 + 150, rule_y + 7),
                        radius=4, fill=R.SAGE)

    sub = R.font('normal', 46)
    lines = ['Every card priced at market.']
    if count:
        lines.append(f'{count} cards. First DM claims it.')
    else:
        lines.append('First DM claims it.')
    y = rule_y + 78
    for ln in lines:
        R.centred(d, y, ln, sub, R.SAGE)
        y += 66

    # The arrow is DRAWN, not typed. The system face has no U+2192 glyph, so
    # 'SWIPE ->' rendered as a tofu box. Same ASCII-only rule as the eBay work.
    cta = R.font('bold', 40)
    txt = 'SWIPE'
    tw = d.textbbox((0, 0), txt, font=cta)[2]
    gap, tri = 26, 22
    total = tw + gap + tri
    bx0 = (R.W - total) // 2 - 46
    d.rounded_rectangle((bx0, R.CTA_TOP, bx0 + total + 92, R.CTA_TOP + 92),
                        radius=46, fill=R.CREAM)
    tx = (R.W - total) // 2
    d.text((tx, R.CTA_TOP + 24), txt, font=cta, fill=R.GREEN)
    ax, ay = tx + tw + gap, R.CTA_TOP + 46
    d.polygon([(ax, ay - tri // 2), (ax + tri, ay), (ax, ay + tri // 2)], fill=R.GREEN)

    bg.save(out, 'JPEG', quality=92)
    print(f'title frame -> {out}')
    return out


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(n)
