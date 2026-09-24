"""Lay out DTP logo + URL for Vistaprint self-inking stamps.

A stamp is one ink, on or off: Vistaprint's stamp tool runs every upload
through a contrast THRESHOLD, which turns anti-aliased edges into jaggies and
fattens thin strokes. So the outputs are hard-edged:
  - vector PDF at the exact stamp size (best - nothing to threshold)
  - 1-bit black-on-white PNG at 1200 dpi (fallback)

The URL is set full width UNDER the logo; side-by-side makes it too small to
ink. The hairline rules either side of the URL are dropped - at stamp size
they are ~0.003in and would not transfer.
"""
import re, sys
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from svgfill import shapes_from, bounds, fill_mask

SRC = sys.argv[1]; OUTDIR = sys.argv[2]
DPI, SS = 1200, 2
svg = open(SRC).read()
g = re.search(r'<g>(.*?)</g>', svg, re.S)
url_shapes = shapes_from(g.group(1))
logo_shapes = shapes_from(svg[:g.start()] + svg[g.end():])

SIZES = {'small': (1.42, 0.47), 'medium': (2.24, 0.83), 'large': (3.00, 1.50)}
MARGIN, GAP = 0.05, 0.045            # inches: edge margin, logo-to-URL gap

lb, ub = bounds(logo_shapes), bounds(url_shapes)
l_ar = (lb[2]-lb[0]) / (lb[3]-lb[1]); u_ar = (ub[2]-ub[0]) / (ub[3]-ub[1])

def layout(name, W, H):
    """Placements in inches, y measured DOWN from the top edge."""
    iw, ih = W - 2*MARGIN, H - 2*MARGIN
    # The small stamp gives the URL a bigger share - at 22% it would be
    # ~0.08in and ink would fill the letters.
    uh = min(iw * 0.92 / u_ar, ih * (0.30 if name == 'small' else 0.22))
    lh = ih - uh - GAP
    lw = lh * l_ar
    if lw > iw: lw = iw; lh = lw / l_ar
    uw = uh * u_ar
    y0 = (H - (lh + GAP + uh)) / 2
    return [(logo_shapes, lb, (W-lw)/2, y0, lh), (url_shapes, ub, (W-uw)/2, y0+lh+GAP, uh)], lw, uw, uh

for name, (W, H) in SIZES.items():
    parts, lw, uw, uh = layout(name, W, H)
    base = f'{OUTDIR}/DTP-stamp-{name}-{W:.2f}x{H:.2f}in'

    # Vector PDF, page = stamp size, even-odd fill keeps letter counters open.
    c = canvas.Canvas(base + '.pdf', pagesize=(W*inch, H*inch))
    c.setFillColorRGB(0, 0, 0)
    for shapes, b, x_in, y_in, h_in in parts:
        s = h_in / (b[3]-b[1])
        for shape in shapes:
            p = c.beginPath()
            for sp in shape:
                pts = [((x_in + (x-b[0])*s) * inch, (H - (y_in + (y-b[1])*s)) * inch) for x, y in sp]
                p.moveTo(*pts[0])
                for q in pts[1:]: p.lineTo(*q)
                p.close()
            c.drawPath(p, fill=1, stroke=0, fillMode=0)   # 0 = even-odd
    c.showPage(); c.save()

    # 1-bit PNG, black on white, no alpha and no grey edges to threshold.
    px = lambda v: v * DPI * SS
    size = (round(px(W)), round(px(H)))
    m = Image.new('L', size, 0)
    from PIL import ImageChops
    for shapes, b, x_in, y_in, h_in in parts:
        s = px(h_in) / (b[3]-b[1])
        fn = lambda x, y, b=b, x_in=x_in, y_in=y_in, s=s: (px(x_in) + (x-b[0])*s, px(y_in) + (y-b[1])*s)
        m = ImageChops.lighter(m, fill_mask(size, shapes, fn))
    m = m.resize((round(W*DPI), round(H*DPI)), Image.LANCZOS)
    bw = m.point(lambda v: 0 if v >= 128 else 255, '1')
    bw.save(base + '.png', dpi=(DPI, DPI))
    print(f'{name:6} {W}x{H}in  logo {lw:.2f}in  URL {uw:.2f}x{uh:.3f}in -> {base}.pdf / .png')
