#!/usr/bin/env python3
"""Make_preview: draw preview.gif, a short Tabata set up, run and recapped.

Development tool only; not part of the app.

    python3 tools/make_preview.py [--out preview.gif]

Presses the keys in KEYS on a simulated clock and draws app.render through
tools/screen.py (which needs reference/), so no emulator or browser is involved
and a countdown second lasts exactly a second. test/differential.test.ts keeps the
JavaScript app's frames equal to these.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import app  # noqa: E402
import screen  # noqa: E402

app.MENU_TYPES = app.TYPES      # the JS app's wheel: SETTINGS is on the bar's Setup page
CONFIG = {"last_type": app.TABATA,
          "types": {app.TABATA: {"work": 3, "rest": 3, "rounds": 2}},
          "get_ready": 3, "sound": True, "step": 1, "skip_with": "ok"}
# s from the start, the key. 1 and -1 are the wheel. Ends on the recap's TOTAL.
KEYS = ((0.8, "ok"), (2.6, "ok"), (3.1, 1), (3.45, 1), (5.2, "ok"), (5.65, "ok"),
        (6.1, "ok"), (6.7, "ok"), (7.6, "start"), (24.9, -1))
END = 26.3
FRAME = 0.05                    # s, 20 fps; a GIF stores hundredths
PITCH, LED = 10, 8              # px per LED and lit px of it: 720x160
PANEL, DARK = (8, 8, 9), (22, 22, 24)


def frames():
    """(grid, seconds on screen), merging frames that show the same."""
    ctrl = app.Controller(app.clean_config(CONFIG))
    keys = list(KEYS)
    shown = []
    for n in range(round(END / FRAME)):
        now = 1000 + n * FRAME
        ctrl.update(now)
        while keys and keys[0][0] <= n * FRAME:
            key = keys.pop(0)[1]
            ctrl.handle(app.Wheel(key, now, False) if isinstance(key, int) else key, now)
        grid = screen.render(app.render(ctrl, now))
        if shown and shown[-1][0] == grid:
            shown[-1][1] += FRAME
        else:
            shown.append([grid, FRAME])
    return shown


def lzw(indexes, min_bits):
    """GIF's LZW, as data sub-blocks."""
    clear, stop = 1 << min_bits, (1 << min_bits) + 1
    table, bits, out, acc, count, prefix = {}, min_bits + 1, bytearray(), 0, 0, None
    next_code = stop + 1

    def emit(code):
        nonlocal acc, count
        acc |= code << count
        count += bits
        while count >= 8:
            out.append(acc & 255)
            acc >>= 8
            count -= 8

    emit(clear)
    for value in indexes:
        if prefix is None:
            prefix = value
        elif (prefix, value) in table:
            prefix = table[prefix, value]
        else:
            emit(prefix)
            table[prefix, value] = next_code
            if next_code == 1 << bits:
                bits += 1
            next_code += 1
            if next_code == 4095:
                emit(clear)
                table, bits, next_code = {}, min_bits + 1, stop + 1
            prefix = value
    emit(prefix)
    if next_code == 1 << bits:  # the decoder has already widened
        bits += 1
    emit(stop)
    if count:
        out.append(acc & 255)
    blocks = bytearray()
    for i in range(0, len(out), 255):
        part = out[i:i + 255]
        blocks += bytes([len(part)]) + part
    return blocks + b"\0"


def pixels(grid, palette):
    margin = (PITCH - LED) // 2
    panel = palette[PANEL]
    rows = []
    for row in grid:
        lit = [panel] * (PITCH * len(row))
        for x, cell in enumerate(row):
            for i in range(margin, margin + LED):
                lit[x * PITCH + i] = palette[cell or DARK]
        blank = [panel] * len(lit)
        rows += [blank] * margin + [lit] * LED + [blank] * margin
    return [value for row in rows for value in row]


def write_gif(shown, path):
    colours = {PANEL, DARK} | {c for grid, _ in shown for row in grid for c in row if c}
    palette = {c: i for i, c in enumerate(sorted(colours))}
    bits = max(2, len(bin(len(palette) - 1)) - 2)
    table = b"".join(bytes(c) for c in sorted(colours)) + bytes(3 * ((1 << bits) - len(palette)))
    width, height = 72 * PITCH, 16 * PITCH
    size = width.to_bytes(2, "little") + height.to_bytes(2, "little")
    with open(path, "wb") as fh:
        fh.write(b"GIF89a" + size + bytes([0xF0 | (bits - 1), 0, 0]) + table)
        fh.write(b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00")
        for grid, seconds in shown:
            delay = round(seconds * 100).to_bytes(2, "little")
            fh.write(b"\x21\xF9\x04\x00" + delay + b"\x00\x00")
            fh.write(b"\x2C\x00\x00\x00\x00" + size + b"\x00" + bytes([bits]))
            fh.write(lzw(pixels(grid, palette), bits))
        fh.write(b"\x3B")


def main():
    parser = argparse.ArgumentParser(description="Draw preview.gif")
    parser.add_argument("--out", default=os.path.join(HERE, "..", "preview.gif"))
    args = parser.parse_args()
    shown = frames()
    write_gif(shown, args.out)
    print(f"{args.out}: {len(shown)} frames, {os.path.getsize(args.out)} bytes")


if __name__ == "__main__":
    main()
