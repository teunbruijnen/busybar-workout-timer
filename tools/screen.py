#!/usr/bin/env python3
"""Screen: render a BUSY Bar frame to a PNG (and ASCII) for checking layouts.

Development tool only; not part of the app.

    python3 tools/screen.py                        # current emulator frame -> screen.png
    python3 tools/screen.py --host 127.0.0.1:8080 --out /tmp/s.png --ascii
    python3 tools/screen.py --json frame.json      # a saved draw body or element list
    python3 tools/screen.py --device 10.0.4.20     # what a real bar shows right now

A port of the emulator's own LED renderer (reference/busybar-emulator/web/src/
lib/{renderer,atlas}.js; MIT, see NOTICE.md), reading its baked font atlas, so text lands on the
same pixels the emulator draws. Like the emulator, it does not draw element
alpha for text, xpmbitmap, images, animations or countdowns; those are listed
as skipped rather than guessed at. Scrolling text is drawn at its start
position.

Checked against the emulator's own PNG export of a calibration
frame (tiny/small/normal/bold/large/extra_large text in six alignments plus a
rectangle): all 72x16 LEDs identical.

From Python: `render(elements)` -> 72x16 grid of (r, g, b) or None,
`to_ascii(grid)`, `write_png(grid, path)`.
"""
import argparse
import base64
import json
import math
import os
import struct
import sys
import urllib.request
import zlib

W, H = 72, 16
HERE = os.path.dirname(os.path.abspath(__file__))
ATLAS_PATH = os.path.join(HERE, "..", "reference", "busybar-emulator", "public",
                          "fonts", "font-atlas.json")

# atlas.js: firmware [ascent, line height] per font; the atlas is ASCII-only so
# its own ascent is smaller, and text is shifted down by the difference.
FW_METRICS = {
    "tiny": (5, 6), "small": (7, 9), "normal": (9, 11), "condensed": (9, 11),
    "bold": (9, 11), "large": (11, 13), "extra_large": (12, 14), "global": (8, 11),
}
ALIGN = {
    "top_left": (0, 0), "top_mid": (0.5, 0), "top_right": (1, 0),
    "mid_left": (0, 0.5), "center": (0.5, 0.5), "mid_right": (1, 0.5),
    "bottom_left": (0, 1), "bottom_mid": (0.5, 1), "bottom_right": (1, 1),
}

_atlas = None


def atlas():
    global _atlas
    if _atlas is None:
        with open(ATLAS_PATH, encoding="utf-8") as fh:
            _atlas = json.load(fh)
    return _atlas


def js_round(v):
    # JavaScript's Math.round: halves round up, also for negatives.
    return math.floor(v + 0.5)


def rasterize(text, font):
    """atlas.js rasterize(): (w, h, set of lit (x, y), advance)."""
    font = font if font in FW_METRICS else "normal"
    f = atlas()[font]
    ascent, line_h = FW_METRICS[font]
    dy_off = ascent - (f.get("ascent") or 0)
    pen = max_right = 0
    parts = []
    for ch in str(text):
        g = f["glyphs"].get(str(ord(ch))) or f["glyphs"].get("63")
        if not g:
            continue
        parts.append((pen, g))
        max_right = max(max_right, pen + g["ox"] + g["w"])
        pen += g["adv"]
    w, h = max(1, pen, max_right), line_h
    lit = set()
    for x0, g in parts:
        for ry in range(g["h"]):
            hexrow = g["rows"][ry] if ry < len(g["rows"]) else ""
            if not hexrow:
                continue
            bits, total, yy = int(hexrow, 16), len(hexrow) * 4, g["oy"] + dy_off + ry
            if not 0 <= yy < h:
                continue
            for rx in range(g["w"]):
                if (bits >> (total - 1 - rx)) & 1:
                    xx = x0 + g["ox"] + rx
                    if 0 <= xx < w:
                        lit.add((xx, yy))
    return w, h, lit, pen


def text_width(text, font):
    """Rendered width in pixels, as the emulator measures it."""
    return rasterize(text, font)[0]


def parse_color(c):
    s = str(c if c is not None else "#FFFFFFFF").strip().lstrip("#")
    if s[:2].lower() == "0x":
        s = s[2:]
    r = g = b = a = 255
    if len(s) >= 6:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    if len(s) >= 8:
        a = int(s[6:8], 16)
    return r, g, b, a / 255


def anchor(el, w, h):
    ax, ay = ALIGN.get(el.get("align"), ALIGN["top_left"])
    return int(el.get("x") or 0) - js_round(w * ax), int(el.get("y") or 0) - js_round(h * ay)


def render(elements, skipped=None):
    """Draw elements in order onto a 72x16 grid (None = off)."""
    grid = [[None] * W for _ in range(H)]

    def px(x, y, rgb, clip=None):
        if 0 <= x < W and 0 <= y < H and (clip is None or clip[0] <= x <= clip[1]):
            grid[y][x] = rgb

    def pxa(x, y, r, g, b, a):
        if a >= 1:
            return px(x, y, (r, g, b))
        if 0 <= x < W and 0 <= y < H:
            old = grid[y][x] or (0, 0, 0)
            grid[y][x] = tuple(round(o * (1 - a) + n * a) for o, n in zip(old, (r, g, b)))

    for el in elements:
        if not isinstance(el, dict) or el.get("display") == "back":
            continue
        kind = el.get("type")
        if kind == "rectangle":
            w, h = int(el.get("width") or 0), int(el.get("height") or 0)
            if w <= 0 or h <= 0:
                continue
            dx, dy = anchor(el, w, h)
            fill, colors = el.get("fill", "none"), el.get("fill_colors") or []
            if fill != "none" and colors:
                c1 = parse_color(colors[0])
                c2 = parse_color(colors[1]) if len(colors) > 1 else c1
                for yy in range(h):
                    for xx in range(w):
                        t = (xx / (w - 1) if fill == "gradient_h" and w > 1 else
                             yy / (h - 1) if fill == "gradient_v" and h > 1 else 0)
                        c = [a + (b - a) * t for a, b in zip(c1, c2)]
                        pxa(dx + xx, dy + yy, *c)
            bw = 1 if el.get("border_width") is None else int(el["border_width"])
            if bw > 0:
                c = parse_color(el.get("border_color") or "#FFFFFFFF")
                for k in range(bw):
                    for xx in range(w):
                        pxa(dx + xx, dy + k, *c)
                        pxa(dx + xx, dy + h - 1 - k, *c)
                    for yy in range(h):
                        pxa(dx + k, dy + yy, *c)
                        pxa(dx + w - 1 - k, dy + yy, *c)
            continue
        if kind != "text":
            if skipped is not None:
                skipped.append("%s (%s)" % (el.get("id"), kind))
            continue
        r, g, b, _ = parse_color(el.get("color"))  # text alpha is ignored, as in the emulator
        w, h, lit, _ = rasterize(el.get("text", ""), el.get("font"))
        clip = None
        if (el.get("scroll_rate") or 0) > 0:
            ax, ay = ALIGN.get(el.get("align"), ALIGN["top_left"])
            box_w = el.get("width") or (W - int(el.get("x") or 0))
            dx = int(el.get("x") or 0) - js_round(box_w * ax)
            dy = int(el.get("y") or 0) - js_round(h * ay)
            clip = (dx, dx + box_w - 1)
        else:
            dx, dy = anchor(el, w, h)
            if el.get("width"):
                clip = (dx, dx + int(el["width"]) - 1)
        for x, y in lit:
            px(dx + x, dy + y, (r, g, b), clip)
    return grid


def to_ascii(grid):
    """One character per LED: '#' lit, '.' off, with a column ruler."""
    tens = "".join(str(x // 10) if x % 10 == 0 else " " for x in range(W))
    ones = "".join(str(x % 10) for x in range(W))
    rows = ["   " + tens, "   " + ones]
    for y, row in enumerate(grid):
        rows.append("%2d %s" % (y, "".join("#" if c else "." for c in row)))
    return "\n".join(rows)


def write_png(grid, path, pitch=10):
    """LED-style PNG: lit cells as squares on a dark panel, 720x160 by default.
    Grids taller than 16 rows are fine (stacked frames); a row of None marks a
    separator, drawn as plain background."""
    bg, gap = (8, 8, 9), max(1, pitch // 5)
    rows, cols = len(grid), len(grid[0])
    raw = bytearray()
    for y in range(rows * pitch):
        raw.append(0)
        cy, iy = divmod(y, pitch)
        row = grid[cy]
        for x in range(cols * pitch):
            cx, ix = divmod(x, pitch)
            if row is None:
                raw += bytes(bg)
                continue
            c = row[cx]
            inside = gap // 2 <= ix < pitch - (gap - gap // 2) and gap // 2 <= iy < pitch - (gap - gap // 2)
            raw += bytes(c if (c and inside) else (bg if not inside else (22, 22, 24)))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", cols * pitch, rows * pitch, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


def device_grid(host, token=None):
    """The real bar's front display as a grid, from GET /api/screen?display=0:
    base64 of 72x16 pixels, three bytes each, ordered BGR (as busylib reads
    it). The pixels are what the LEDs show, so nothing is re-rendered."""
    base = "http://" + host.replace("http://", "").rstrip("/")
    req = urllib.request.Request(base + "/api/screen?display=0",
                                 headers={"X-API-Token": token} if token else {})
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = base64.b64decode(resp.read())
    if len(raw) != W * H * 3:
        raise ValueError("expected %d bytes of BGR pixels, got %d" % (W * H * 3, len(raw)))
    grid = [[None] * W for _ in range(H)]
    for i in range(W * H):
        b, g, r = raw[3 * i:3 * i + 3]
        if r or g or b:
            grid[i // W][i % W] = (r, g, b)
    return grid


def emulator_elements(host):
    """The frame the emulator is showing, from the first state event on /events."""
    base = "http://" + host.replace("http://", "").rstrip("/")
    with urllib.request.urlopen(base + "/events", timeout=5) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:"):
                state = json.loads(line[5:])
                frame = state.get("frame") or {}
                return frame.get("elements") or [], frame.get("application_name")
    return [], None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="127.0.0.1:8080", help="emulator address")
    p.add_argument("--json", help="read a draw body or element list from this file instead")
    p.add_argument("--device", metavar="HOST",
                   help="capture a real bar's screen instead (e.g. 10.0.4.20 over USB)")
    p.add_argument("--token", default=os.environ.get("BUSY_HTTP_PASSWORD"),
                   help="Wi-Fi API password for --device (default: $BUSY_HTTP_PASSWORD)")
    p.add_argument("--out", default="screen.png", help="PNG path (default screen.png)")
    p.add_argument("--ascii", action="store_true", help="also print the frame as ASCII")
    args = p.parse_args(argv)

    if args.device:
        grid = device_grid(args.device, args.token)
        write_png(grid, args.out)
        print("screen: %s -> %s" % (args.device, args.out))
        if args.ascii:
            print(to_ascii(grid))
        return 0
    if args.json:
        with open(args.json, encoding="utf-8") as fh:
            data = json.load(fh)
        elements, owner = (data.get("elements", []), data.get("application_name")) \
            if isinstance(data, dict) else (data, None)
    else:
        elements, owner = emulator_elements(args.host)

    skipped = []
    grid = render(elements, skipped)
    write_png(grid, args.out)
    print("%s: %d element(s) from %s -> %s" % (
        "screen", len(elements), owner or "(nobody)", args.out))
    if skipped:
        print("not drawn (unsupported here and in the emulator): " + ", ".join(skipped))
    if args.ascii:
        print(to_ascii(grid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
