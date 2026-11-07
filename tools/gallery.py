#!/usr/bin/env python3
"""Gallery: render every screen state into one stacked PNG.

Development tool only; not part of the app.

    python3 tools/gallery.py --out /tmp/gallery.png         # all states
    python3 tools/gallery.py --out /tmp/g.png --ascii pause # + ASCII of matching states

States are rendered straight from app.render_* through tools/screen.py
(which needs reference/, but no bar or running emulator), top to bottom in the order printed.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import app  # noqa: E402
import screen  # noqa: E402

T0 = 1000.0


def at(kind, t, pause_at=None, rounds=8, work=20, rest=10, get_ready=5, skips=(), **kw):
    """A workout started at T0 and observed at T0 + t; `skips` are skip
    presses (seconds after T0) that each end a phase, `pause_at` pauses it."""
    w = app.Workout(kind, work=work, rest=rest, rounds=rounds, get_ready=get_ready)
    w.start(T0)
    for skip in skips:
        w.advance(T0 + skip)
    if pause_at is not None:
        w.toggle_pause(T0 + pause_at)
    w.update(T0 + t)
    return app.render_workout(w, T0 + t, **kw)


def recap(page, kind=app.TABATA, rounds=8, stop_at=None, **kw):
    """The recap page of a 20/10 workout that ran to its end, or was stopped
    `stop_at` seconds after T0."""
    w = app.Workout(kind, work=kw.get("work", 20), rest=kw.get("rest", 10),
                    rounds=rounds, get_ready=5)
    w.start(T0)
    if stop_at is None:
        w.update(T0 + 10 ** 6)
    else:
        w.update(T0 + stop_at)
        w.stop(T0 + stop_at)
    return app.render_recap(w, page)


def _widest():
    # FIX_REST, round 12 of 99, open WORK running past the 99:59 cap.
    w = app.Workout(app.FIX_REST, rest=10, rounds=99, get_ready=0)
    w.start(T0)
    t = T0
    for _ in range(11):
        t += 30
        w.advance(t)          # end WORK
        t += 10
        w.update(t)           # REST ends
    return app.render_workout(w, t + 2 * 3600)


def menu(field, choice=None, kind=app.TABATA, hidden_part=None, **values):
    """A menu field, with a time's `hidden_part` blinked off; `values`
    override the timer type's settings (work/rest/rounds) or the shared ones
    (get_ready/sound/step/skip_with)."""
    cfg = app.default_config()
    cfg["last_type"] = kind
    for key, value in values.items():
        (cfg["types"][kind] if key in ("work", "rest", "rounds") else cfg)[key] = value
    return app.render_menu(cfg, field, choice or kind, hidden_part)


def summary(kind=app.TABATA, **values):
    cfg = app.default_config()
    cfg["last_type"] = kind
    cfg["types"][kind].update(values)
    return app.render_summary(cfg)


STATES = [
    ("menu: type TABATA", lambda: menu("type")),
    ("menu: type FIXED REST", lambda: menu("type", app.FIX_REST)),
    ("menu: type FIXED WORK", lambda: menu("type", app.FIX_WORK)),
    ("menu: type SETTINGS", lambda: menu("type", app.SETTINGS)),
    ("menu: work 0:20", lambda: menu("work")),
    ("menu: work 0:20, minutes off", lambda: menu("work", hidden_part=app.MINUTES)),
    ("menu: work 0:20, seconds off", lambda: menu("work", hidden_part=app.SECONDS)),
    ("menu: rounds 8", lambda: menu("rounds")),
    ("menu: rounds unlimited", lambda: menu("rounds", rounds=None)),
    ("menu: rest 1:30, fix rest", lambda: menu("rest", kind=app.FIX_REST, rest=90)),
    ("menu: work 0:45, fix work", lambda: menu("work", kind=app.FIX_WORK, work=45)),
    ("menu: work 59:59", lambda: menu("work", work=3599)),
    ("menu: work 59:59, minutes off", lambda: menu("work", work=3599, hidden_part=app.MINUTES)),
    ("menu: work 59:59, seconds off", lambda: menu("work", work=3599, hidden_part=app.SECONDS)),
    ("menu: rounds 5, fix work", lambda: menu("rounds", kind=app.FIX_WORK, rounds=5)),
    ("menu: get ready 15 sec", lambda: menu("get_ready", get_ready=15)),
    ("menu: get ready off", lambda: menu("get_ready", get_ready=0)),
    ("menu: sound on", lambda: menu("sound")),
    ("menu: step 10 sec", lambda: menu("step", step=10)),
    ("menu: skip with OK", lambda: menu("skip_with")),
    ("menu: skip with START", lambda: menu("skip_with", skip_with="start")),
    ("summary: 20/10 x8", lambda: summary()),
    ("summary: unlimited 20/10 x inf", lambda: summary(rounds=None)),
    ("summary: fix rest 1:30 x5", lambda: summary(app.FIX_REST, rest=90, rounds=5)),
    ("summary: fix work 1:30 x12", lambda: summary(app.FIX_WORK, work=90, rounds=12)),
    ("summary: widest 59:59/59:59 x99", lambda: summary(work=3599, rest=3599, rounds=99)),
    ("summary: widest unlimited", lambda: summary(work=3599, rest=3599, rounds=None)),

    ("get ready 5", lambda: at(app.TABATA, 0.4)),
    ("get ready 3, blink on", lambda: at(app.TABATA, 2.05)),
    ("get ready 3, blink off", lambda: at(app.TABATA, 2.6)),
    ("work begins", lambda: at(app.TABATA, 5.1)),
    ("work 0:17, bar", lambda: at(app.TABATA, 8.5)),
    ("work 0:02, blink on", lambda: at(app.TABATA, 23.3)),
    ("work 0:02, last digit off", lambda: at(app.TABATA, 23.7)),
    ("rest 0:07", lambda: at(app.TABATA, 28.5)),
    ("paused, blink on", lambda: at(app.TABATA, 12.2, pause_at=12)),
    ("paused, blink off", lambda: at(app.TABATA, 12.7, pause_at=12)),
    ("stop? during work", lambda: at(app.TABATA, 9.5, confirm_stop=True)),
    ("fix rest: open work +0:42", lambda: at(app.FIX_REST, 47.3)),
    ("fix work: open rest +1:05", lambda: at(app.FIX_WORK, 90.2)),
    ("unlimited: R12", lambda: at(app.TABATA, 5 + 11 * 30 + 3, rounds=None)),
    ("widest: +99:59, 12/99", lambda: _widest()),
    ("long fixed: 59:59, 1/99", lambda: at(app.TABATA, 5.5, work=3599, rounds=99)),
    ("recap: work 2:40, done", lambda: recap("work")),
    ("recap: rest 1:10", lambda: recap("rest")),
    ("recap: rounds 8/8", lambda: recap("rounds")),
    ("recap: total 3:50", lambda: recap("total")),
    ("recap: stopped, rounds 3/8", lambda: recap("rounds", stop_at=5 + 3 * 30 + 12)),
    ("recap: unlimited, rounds 41", lambda: recap("rounds", rounds=None, stop_at=5 + 41 * 30 + 4)),
    ("recap: total over an hour 1:42:05", lambda: recap("total", rounds=None, stop_at=5 + 6125)),
    ("recap: widest, total 10:00:00+", lambda: recap("total", kind=app.FIX_REST, rounds=None,
                                                     rest=3595, stop_at=5 + 36005)),
]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default="gallery.png")
    p.add_argument("--ascii", metavar="MATCH", help="print ASCII for states containing MATCH")
    args = p.parse_args(argv)

    stacked = []
    for i, (name, make) in enumerate(STATES):
        grid = screen.render(make())
        if stacked:
            stacked.append(None)          # separator row
        stacked.extend(grid)
        print("%2d  %s" % (i + 1, name))
        if args.ascii and args.ascii in name:
            print(screen.to_ascii(grid))
    screen.write_png(stacked, args.out, pitch=6)
    print("-> %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
