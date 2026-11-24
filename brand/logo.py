#!/usr/bin/env python3
"""logo.py - the Push Gate logo, drawn from its measures into brand/ and docs/.

A field gate shut across the way of a push: a sapphire dot, the push, behind an off-white gate of two posts, two rails,
and a brace; on near-black. The Haedo Labs product family's measures: a square of 64, the dot's radius 15.6 at the
centre, lines 3.25 wide with round ends, inside 6..58.

    python3 brand/logo.py        writes brand/: logo.svg (rounded), logo-square.svg (square, for places that round or
                                 crop a picture themselves), mark.svg (the dot and the gate alone, to lay on a page),
                                 PNGs at 1024, 400, 180, and 32 pixels; and docs/icon.png (180, rounded) for the README

Standard library only: the PNGs are drawn here, each pixel's coverage from its distance to each shape.
"""
import math, os, struct, sys, zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'brand')

NEAR_BLACK, SAPPHIRE, OFF_WHITE = (0x11, 0x11, 0x10), (0x0f, 0x52, 0xba), (0xec, 0xe7, 0xdf)
CORNER = 14                          # the square's corner radius
DOT = 15.6                           # the dot's radius, at the centre: the push
WIDTH = 3.25                         # the lines' width, round ends
A, B = 6, 58                         # the lines stay inside 6..58
TOP, BOTTOM = 16, 48                 # the rails' heights

# The gate: two posts, two rails, and the brace from the bottom rail at the hinge post to the top rail at the latch.
SEGMENTS = [((A, A), (A, B)), ((B, A), (B, B)), ((A, TOP), (B, TOP)), ((A, BOTTOM), (B, BOTTOM)),
            ((A, BOTTOM), (B, TOP))]


def hexc(c):
    return '#%02x%02x%02x' % c


def svg(background=True, rounded=True):
    back = ''
    if background:
        corner = f' rx="{CORNER}"' if rounded else ''
        back = f'<rect width="64" height="64"{corner} fill="{hexc(NEAR_BLACK)}"/>'
    lines = ''.join(f'<path d="M{x0} {y0}L{x1} {y1}"/>' for (x0, y0), (x1, y1) in SEGMENTS)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">{back}'
            f'<circle cx="32" cy="32" r="{DOT}" fill="{hexc(SAPPHIRE)}"/>'
            f'<g fill="none" stroke="{hexc(OFF_WHITE)}" stroke-width="{WIDTH}" stroke-linecap="round" stroke-linejoin="round">'
            f'{lines}</g></svg>\n')


def segment_distance(x, y, seg):
    """Distance from (x, y) to a segment's centre line."""
    (x0, y0), (x1, y1) = seg
    dx, dy = x1 - x0, y1 - y0
    t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x0 + t * dx), y - (y0 + t * dy))


def png(side, rounded=True):
    """The logo as a PNG side x side, antialiased by distance: coverage = clamp(0.5 - distance in pixels)."""
    k = side / 64
    def cover(d): return min(1.0, max(0.0, 0.5 - d * k))
    rows = []
    for py in range(side):
        y = (py + 0.5) / k
        row = bytearray()
        for px in range(side):
            x = (px + 0.5) / k
            if rounded:                                    # the rounded square's distance
                qx, qy = abs(x - 32) - (32 - CORNER), abs(y - 32) - (32 - CORNER)
                d = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - CORNER
                alpha = cover(d)
            else:
                alpha = 1.0
            col = list(NEAR_BLACK)
            for shape, c in ((math.hypot(x - 32, y - 32) - DOT, SAPPHIRE),
                             (min(segment_distance(x, y, s) for s in SEGMENTS) - WIDTH / 2, OFF_WHITE)):
                a = cover(shape)
                if a: col = [col[i] + (c[i] - col[i]) * a for i in range(3)]
            row += bytes(round(v) for v in col) + bytes([round(255 * alpha)])
        rows.append(b'\x00' + bytes(row))
    def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', side, side, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows), 9)) + chunk(b'IEND', b''))


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(ROOT, 'docs'), exist_ok=True)
    files = {'logo.svg': svg(), 'logo-square.svg': svg(rounded=False), 'mark.svg': svg(background=False)}
    for name, text in files.items():
        with open(os.path.join(OUT, name), 'w') as f:
            f.write(text)
    pngs = (('brand/logo-1024.png', 1024, True), ('brand/logo-180.png', 180, True), ('brand/logo-32.png', 32, True),
            ('brand/logo-square-1024.png', 1024, False), ('brand/logo-square-400.png', 400, False),
            ('brand/logo-square-180.png', 180, False), ('docs/icon.png', 180, True))
    for name, side, rounded in pngs:
        with open(os.path.join(ROOT, name), 'wb') as f:
            f.write(png(side, rounded))
    print(f'logo: {len(files) + len(pngs)} files in brand/ and docs/')
    return 0


if __name__ == '__main__':
    sys.exit(main())
