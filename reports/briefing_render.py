#!/usr/bin/env python3
"""
Rendering for the morning briefing.

The briefing is built once as a list of Sections and rendered twice — plain
text for the terminal and the saved copy, HTML for the email. Building it twice
would let the two drift, and the one that drifts is always the one you only
ever see on a phone.

Email HTML is not web HTML. Gmail strips <style> blocks in some clients, Outlook
renders through Word, and neither honours flexbox or grid. So: tables for
layout, inline styles on every element, no shorthand backgrounds, explicit
widths. It looks like 2005 because it has to.
"""

# Palette lifted from public/css/styles.css so the email reads as the same
# business as the site.
FOREST      = '#0F3C1F'
FOREST_DARK = '#0A2814'
CREAM       = '#F7F4EB'
BORDER      = '#DCD6C4'
TEXT        = '#16281C'
MUTED       = '#4A5750'
GOOD        = '#1B7A3D'
BAD         = '#A32020'
WARN        = '#9A6212'

TONES = {
    'good':  GOOD,
    'bad':   BAD,
    'warn':  WARN,
    'info':  FOREST,
    'muted': MUTED,
}

MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


class Section:
    """One block of the briefing.

    rows are lists of cells. A cell is either a string or a (text, tone) pair
    when a single value needs its own colour — a negative P/L in an otherwise
    neutral table, for instance.
    """

    def __init__(self, title, tone='info', subtitle=None, cols=None,
                 rows=None, footnote=None, empty=None, text_prefix='──'):
        self.title = title
        self.tone = tone
        self.subtitle = subtitle
        self.cols = cols or []          # list of (label, align) where align is l|r
        self.rows = rows or []
        self.footnote = footnote
        self.empty = empty
        self.text_prefix = text_prefix


def _cell(c):
    return c if isinstance(c, tuple) else (c, None)


# --- plain text ---------------------------------------------------------------

def render_text(title, meta, sections):
    out = [title]
    if meta:
        out.append(meta)
    out.append('')

    for s in sections:
        if not s.rows and not s.empty:
            continue
        head = f"{s.text_prefix} {s.title}"
        out.append(head)
        if s.subtitle:
            out.append(f"   {s.subtitle}")
        if not s.rows:
            out.append(f"   {s.empty}")
        else:
            # Width of the widest of the header and every cell, so the header
            # never overhangs its own column.
            widths = [max([len(_cell(r[i])[0]) for r in s.rows] + [len(label)])
                      for i, (label, _) in enumerate(s.cols)]

            def line(cells, pad=' '):
                bits = []
                for i, (label, align) in enumerate(s.cols):
                    t = cells[i]
                    bits.append(t.rjust(widths[i], pad) if align == 'r'
                                else t.ljust(widths[i], pad))
                return '   ' + '  '.join(bits).rstrip()

            # Two columns are self-evident (a number and a card). Three or more
            # are not — "$150.00  $170.00  $203.43" needs saying which is which.
            if len(s.cols) >= 3:
                out.append(line([c[0] for c in s.cols]))
                out.append(line(['' for _ in s.cols], pad='-'))

            for r in s.rows:
                out.append(line([_cell(r[i])[0] for i in range(len(s.cols))]))
        if s.footnote:
            out.append(f"   {s.footnote}")
        out.append('')

    return '\n'.join(out).rstrip() + '\n'


# --- html ---------------------------------------------------------------------

def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def render_html(title, meta, sections, stats=None):
    p = []
    a = p.append

    a('<!doctype html><html><head><meta charset="utf-8">')
    a('<meta name="viewport" content="width=device-width,initial-scale=1">')
    # Tells clients not to invert the palette themselves, which is what turns a
    # cream email into unreadable grey-on-grey in dark mode.
    a('<meta name="color-scheme" content="light only">')
    a('<meta name="supported-color-schemes" content="light only">')
    a(f'<title>{esc(title)}</title></head>')
    a(f'<body style="margin:0;padding:0;background:{CREAM};'
      f'-webkit-text-size-adjust:100%;">')

    a(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
      f'border="0" style="background:{CREAM};"><tr><td align="center" '
      f'style="padding:20px 12px;">')
    a('<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
      'border="0" style="width:600px;max-width:100%;">')

    # --- masthead
    a(f'<tr><td style="background:{FOREST};padding:22px 24px;border-radius:10px 10px 0 0;">')
    a(f'<div style="font:700 11px/1 {SANS};letter-spacing:.16em;'
      f'text-transform:uppercase;color:#9FD4B2;">Duxbury Trading Post</div>')
    a(f'<div style="font:600 22px/1.25 {SANS};color:#FFFFFF;padding-top:7px;">'
      f'Morning briefing</div>')
    if meta:
        a(f'<div style="font:400 13px/1.4 {SANS};color:#B9D9C6;padding-top:4px;">'
          f'{esc(meta)}</div>')
    a('</td></tr>')

    # --- headline numbers
    if stats:
        a(f'<tr><td style="background:{FOREST_DARK};padding:0 12px 16px;">')
        a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>')
        for label, value, tone in stats:
            col = {'good': '#7FE0A0', 'bad': '#FF9B9B'}.get(tone, '#FFFFFF')
            a(f'<td align="center" style="padding:10px 6px;">'
              f'<div style="font:600 19px/1.2 {MONO};color:{col};">{esc(value)}</div>'
              f'<div style="font:400 10px/1.3 {SANS};letter-spacing:.08em;'
              f'text-transform:uppercase;color:#8FB79E;padding-top:3px;">{esc(label)}</div>'
              f'</td>')
        a('</tr></table></td></tr>')

    # --- sections
    a(f'<tr><td style="background:#FFFFFF;padding:6px 0 4px;'
      f'border-left:1px solid {BORDER};border-right:1px solid {BORDER};">')

    any_section = False
    for s in sections:
        if not s.rows and not s.empty:
            continue
        any_section = True
        accent = TONES.get(s.tone, FOREST)

        a(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
          f'border="0" style="margin:14px 0;"><tr><td '
          f'style="padding:0 20px 0 16px;border-left:3px solid {accent};">')

        a(f'<div style="font:700 12px/1.3 {SANS};letter-spacing:.09em;'
          f'text-transform:uppercase;color:{accent};">{esc(s.title)}</div>')
        if s.subtitle:
            a(f'<div style="font:400 12px/1.5 {SANS};color:{MUTED};padding-top:4px;">'
              f'{esc(s.subtitle)}</div>')

        if not s.rows:
            a(f'<div style="font:400 13px/1.5 {SANS};color:{MUTED};padding-top:6px;">'
              f'{esc(s.empty)}</div>')
        else:
            a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
              'border="0" style="padding-top:8px;">')
            # Same rule as the text renderer: two columns explain themselves,
            # three columns of dollar amounts do not.
            if len(s.cols) >= 3:
                a('<tr>')
                for label, align in s.cols:
                    a(f'<td align="{"right" if align == "r" else "left"}" '
                      f'style="font:700 9px/1.4 {SANS};letter-spacing:.08em;'
                      f'text-transform:uppercase;color:{MUTED};padding:0 8px 4px;'
                      f'border-bottom:1px solid {BORDER};white-space:nowrap;">'
                      f'{esc(label)}</td>')
                a('</tr>')
            for ri, r in enumerate(s.rows):
                bg = '#FFFFFF' if ri % 2 == 0 else '#FAF9F4'
                a('<tr>')
                for i, (label, align) in enumerate(s.cols):
                    txt, tone = _cell(r[i])
                    col = TONES.get(tone, TEXT) if tone else TEXT
                    # Numbers get the monospace face so columns line up; the
                    # last column is always the card name and gets the sans.
                    face = SANS if align == 'l' and i == len(s.cols) - 1 else MONO
                    weight = 600 if tone else 400
                    # Only the last column — always the card name — is allowed
                    # to wrap. Everything else is a short label or a number, and
                    # letting those wrap breaks "under break-even" across two
                    # lines with a hyphen that looks like part of the value.
                    last = i == len(s.cols) - 1
                    a(f'<td align="{"right" if align == "r" else "left"}" '
                      f'style="background:{bg};font:{weight} 12px/1.5 {face};'
                      f'color:{col};padding:5px 8px;'
                      f'border-bottom:1px solid #F0EDE3;'
                      f'{"" if last else "white-space:nowrap;"}'
                      f'{"width:99%;" if last else ""}">'
                      f'{esc(txt)}</td>')
                a('</tr>')
            a('</table>')

        if s.footnote:
            a(f'<div style="font:400 11px/1.5 {SANS};color:{MUTED};padding-top:7px;'
              f'font-style:italic;">{esc(s.footnote)}</div>')
        a('</td></tr></table>')

    if not any_section:
        a(f'<div style="font:400 14px/1.6 {SANS};color:{MUTED};padding:26px 20px;'
          f'text-align:center;">Nothing needs you this morning.</div>')

    a('</td></tr>')

    # --- footer
    a(f'<tr><td style="background:{CREAM};border:1px solid {BORDER};'
      f'border-radius:0 0 10px 10px;padding:14px 20px;">')
    a(f'<div style="font:400 11px/1.6 {SANS};color:{MUTED};">'
      f'Generated locally by <span style="font-family:{MONO};">reports/daily-briefing.py</span> '
      f'and sent through duxburytradingpost.com. '
      f'Break-even assumes 13.25% eBay fees, the per-order fee, and ESE at $0.78 '
      f'up to $19.22 or Ground Advantage above it.</div>')
    a('</td></tr>')

    a('</table></td></tr></table></body></html>')
    return '\n'.join(p)
