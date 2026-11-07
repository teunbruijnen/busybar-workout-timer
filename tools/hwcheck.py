#!/usr/bin/env python3
"""Hwcheck: draw every gallery screen on a real bar and compare its LEDs.

Development tool only; not part of the app.

    python3 tools/hwcheck.py                   # bar over USB (10.0.4.20)
    python3 tools/hwcheck.py --host 192.168.1.50 --token ...

Each state from tools/gallery.py is drawn on the bar as the workout-timer app,
read back with GET /api/screen, and compared pixel by pixel (colour included)
with tools/screen.py's rendering of the same elements, which is what the
emulator shows. Stop the app first: both would draw under the same name.
The display is cleared at the end.
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import app  # noqa: E402
import gallery  # noqa: E402
import screen  # noqa: E402

SETTLE = 0.15          # s between reads while waiting for the frame to land
TRIES = 10


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="10.0.4.20")
    p.add_argument("--token", default=os.environ.get("BUSY_HTTP_PASSWORD"))
    p.add_argument("--match", help="only states whose name contains this")
    args = p.parse_args(argv)

    problems = []
    bar = app.Bar(args.host, args.token, log=problems.append)
    bar.clear()
    states = [s for s in gallery.STATES if not args.match or args.match in s[0]]
    failed = 0
    try:
        for name, make in states:
            elements = make()
            if not bar.draw(elements):
                failed += 1
                print("FAIL  %-40s draw refused: %s" % (name, problems[-1] if problems else "?"))
                continue
            want = screen.render(elements)
            for _ in range(TRIES):
                time.sleep(SETTLE)
                got = screen.device_grid(args.host, args.token)
                diff = [(x, y) for y in range(app.H) for x in range(app.W)
                        if want[y][x] != got[y][x]]
                if not diff:
                    break
            if diff:
                failed += 1
                print("FAIL  %-40s %d LEDs differ, first at %s" % (name, len(diff), diff[:3]))
                print("      expected:\n" + screen.to_ascii(want))
                print("      bar:\n" + screen.to_ascii(got))
            else:
                print("ok    %s" % name)
    finally:
        bar.clear()
    print("%d of %d screens differ" % (failed, len(states)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
