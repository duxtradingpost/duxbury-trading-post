"""Render public/images/logo.svg to transparent PNGs (no SVG library needed).

Parses the logo's <path>/<polygon> elements (M/L/H/V/C/S/Z, abs+rel),
flattens the curves, fills them in brand green on a transparent canvas at
4x supersampling, then downsamples for smooth edges.
"""
import re, sys
from PIL import Image, ImageDraw

SVG = sys.argv[1]
OUT_LOGO = sys.argv[2]        # logo only, trimmed, transparent
OUT_STICKER = sys.argv[3]     # 1.5" circle sticker layout, transparent
GREEN = (0x1C, 0x3A, 0x23, 255)
DPI = 600
SS = 4                        # supersampling factor

src = open(SVG).read()

def tokens(d):
    return re.findall(r'[MmLlHhVvCcSsZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?', d)

def bez(p0, p1, p2, p3, n=24):
    out = []
    for i in range(1, n + 1):
        t = i / n; u = 1 - t
        out.append((u**3*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0],
                    u**3*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1]))
    return out

def path_to_polys(d):
    tk = tokens(d); i = 0; cmd = None
    cur = (0.0, 0.0); start = cur; last_c2 = None
    polys, poly = [], []
    def num():
        nonlocal i
        v = float(tk[i]); i += 1; return v
    while i < len(tk):
        if re.match(r'[A-Za-z]', tk[i]):
            cmd = tk[i]; i += 1
        rel = cmd.islower(); c = cmd.upper()
        ox, oy = cur if rel else (0.0, 0.0)
        if c == 'Z':
            if poly: polys.append(poly); poly = []
            cur = start; last_c2 = None; continue
        if c == 'M':
            if poly: polys.append(poly)
            cur = (ox + num(), oy + num()); start = cur; poly = [cur]
            cmd = 'l' if rel else 'L'; last_c2 = None
        elif c == 'L':
            cur = (ox + num(), oy + num()); poly.append(cur); last_c2 = None
        elif c == 'H':
            cur = ((cur[0] if rel else 0) + num(), cur[1]); poly.append(cur); last_c2 = None
        elif c == 'V':
            cur = (cur[0], (cur[1] if rel else 0) + num()); poly.append(cur); last_c2 = None
        elif c == 'C':
            p1 = (ox + num(), oy + num()); p2 = (ox + num(), oy + num()); p3 = (ox + num(), oy + num())
            poly += bez(cur, p1, p2, p3); last_c2 = p2; cur = p3
        elif c == 'S':
            p1 = (2*cur[0] - last_c2[0], 2*cur[1] - last_c2[1]) if last_c2 else cur
            p2 = (ox + num(), oy + num()); p3 = (ox + num(), oy + num())
            poly += bez(cur, p1, p2, p3); last_c2 = p2; cur = p3
    if poly: polys.append(poly)
    return polys

shapes = []
for d in re.findall(r'<path[^>]*\sd="([^"]+)"', src):
    shapes += path_to_polys(d)
for pts in re.findall(r'<polygon[^>]*\spoints="([^"]+)"', src):
    v = [float(x) for x in pts.split()]
    shapes.append(list(zip(v[0::2], v[1::2])))

xs = [p[0] for s in shapes for p in s]; ys = [p[1] for s in shapes for p in s]
minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
aspect = (maxx - minx) / (maxy - miny)

def draw_logo(width_px):
    """Logo trimmed to its own bounds, width_px wide, transparent."""
    scale = width_px * SS / (maxx - minx)
    W = round((maxx - minx) * scale); H = round((maxy - miny) * scale)
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    for s in shapes:
        dr.polygon([((x - minx) * scale, (y - miny) * scale) for x, y in s], fill=GREEN)
    return im.resize((W // SS, H // SS), Image.LANCZOS)

# 1) Plain logo, 3000px wide (5" at 600 dpi) - scales down cleanly for anything.
logo = draw_logo(3000)
logo.save(OUT_LOGO, dpi=(DPI, DPI))
print('logo', logo.size, 'aspect %.3f' % aspect)

# 2) Sticker layout: 1.5" circle that folds over the toploader's top edge.
#    Bottom half = front of the toploader, top half wraps over to the back,
#    so the logo sits upright in the BOTTOM half, clear of the fold line.
# Vistaprint's 1.5" circle canvas is 1.62" (0.06" bleed all round) and its
# safety circle is ~1.38" across, so size the file to the CANVAS and keep the
# logo inside a 0.64" radius - uploading a 1.5" file gets stretched 8% to fit.
D = int(1.62 * DPI)                   # 972 px
r_safe = 0.64 * DPI                   # inside Vistaprint's ~0.69" safety radius
gap = 0.08 * DPI                      # keep 0.08" below the fold line
# largest logo height h whose top corners stay inside the safe circle
h = 0
while True:
    nh = h + 1; w = nh * aspect
    if (w / 2) ** 2 + (gap + nh) ** 2 > r_safe ** 2: break
    h = nh
lw = int(h * aspect)
sticker = Image.new('RGBA', (D, D), (0, 0, 0, 0))
lg = draw_logo(lw)
sticker.alpha_composite(lg, (int(D / 2 - lg.width / 2), int(D / 2 + gap)))
sticker.save(OUT_STICKER, dpi=(DPI, DPI))
print('sticker', sticker.size, 'logo %.2f" x %.2f"' % (lg.width / DPI, lg.height / DPI))
