"""Minimal SVG path filler for the DTP logo files (no SVG library on this Mac).

Handles M/L/H/V/C/S/Z (abs + rel) paths and polygons, flattens curves, and
fills each <path> EVEN-ODD so letter counters (d, o, p, g) stay open.
"""
import re
from PIL import Image, ImageDraw, ImageChops

def _tokens(d):
    return re.findall(r'[MmLlHhVvCcSsZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?', d)

def _bez(p0, p1, p2, p3, n=24):
    return [((1-t)**3*p0[0] + 3*(1-t)**2*t*p1[0] + 3*(1-t)*t*t*p2[0] + t**3*p3[0],
             (1-t)**3*p0[1] + 3*(1-t)**2*t*p1[1] + 3*(1-t)*t*t*p2[1] + t**3*p3[1])
            for t in (i / n for i in range(1, n + 1))]

def path_subpaths(d):
    tk = _tokens(d); i = 0; cmd = None
    cur = start = (0.0, 0.0); last_c2 = None; polys, poly = [], []
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
            cur = start = (ox + num(), oy + num()); poly = [cur]
            cmd = 'l' if rel else 'L'; last_c2 = None
        elif c == 'L':
            cur = (ox + num(), oy + num()); poly.append(cur); last_c2 = None
        elif c == 'H':
            cur = ((cur[0] if rel else 0) + num(), cur[1]); poly.append(cur); last_c2 = None
        elif c == 'V':
            cur = (cur[0], (cur[1] if rel else 0) + num()); poly.append(cur); last_c2 = None
        elif c == 'C':
            p1 = (ox+num(), oy+num()); p2 = (ox+num(), oy+num()); p3 = (ox+num(), oy+num())
            poly += _bez(cur, p1, p2, p3); last_c2 = p2; cur = p3
        elif c == 'S':
            p1 = (2*cur[0]-last_c2[0], 2*cur[1]-last_c2[1]) if last_c2 else cur
            p2 = (ox+num(), oy+num()); p3 = (ox+num(), oy+num())
            poly += _bez(cur, p1, p2, p3); last_c2 = p2; cur = p3
    if poly: polys.append(poly)
    return polys

def shapes_from(svg_fragment):
    """List of shapes; each shape is a list of subpath polygons."""
    out = [path_subpaths(d) for d in re.findall(r'<path[^>]*\sd="([^"]+)"', svg_fragment)]
    for pts in re.findall(r'<polygon[^>]*\spoints="([^"]+)"', svg_fragment):
        v = [float(x) for x in pts.split()]
        out.append([list(zip(v[0::2], v[1::2]))])
    return out

def bounds(shapes):
    xs = [p[0] for s in shapes for sp in s for p in sp]
    ys = [p[1] for s in shapes for sp in s for p in sp]
    return min(xs), min(ys), max(xs), max(ys)

def fill_mask(size, shapes, fn):
    """Coverage mask ('L') for shapes mapped through fn(x,y)->(px,py)."""
    acc = Image.new('L', size, 0)
    for s in shapes:
        m = Image.new('L', size, 0)
        for sp in s:
            one = Image.new('L', size, 0)
            ImageDraw.Draw(one).polygon([fn(x, y) for x, y in sp], fill=255)
            m = ImageChops.difference(m, one)          # even-odd
        acc = ImageChops.lighter(acc, m)               # union of shapes
    return acc
