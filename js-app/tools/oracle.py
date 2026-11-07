#!/usr/bin/env python3
"""Runs ../app.py, the behaviour reference, through seeded random sessions and prints
what it did as JSON, one line per step. test/differential.test.ts replays the same
inputs through the TypeScript port and compares everything."""
import json
import os
import random
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import app  # noqa: E402

# The JS app has no SETTINGS on its wheel: those moved to the bar's Setup page. Their values
# still come in with the config.
app.MENU_TYPES = app.TYPES

GAPS_MS = (0, 10, 40, 79, 80, 81, 100, 100, 100, 300, 499, 500, 501, 700, 999, 1000,
           1001, 1100, 2500, 3000, 3001, 10000, 61000, 700000, 3700000, 40000000)
EVENTS = ("ok",) * 6 + ("start",) * 6 + ("back",) * 3 + (1, 1, 1, -1, -1, None, None, None)


def random_config(rng):
    def time_value():
        return rng.choice((1, 2, 3, 4, 5, 7, 10, 20, 59, 60, 61, 90, 600, 3599))
    return app.clean_config({
        "last_type": rng.choice(app.TYPES),
        "types": {kind: {"work": time_value(), "rest": time_value(),
                         "rounds": rng.choice((1, 2, 3, 8, 12, 99, None))}
                  for kind in app.TYPES},
        "get_ready": rng.choice((0, 1, 2, 3, 5, 15)),
        "sound": rng.random() < 0.8,
        "step": rng.choice(app.STEPS),
        "skip_with": rng.choice(app.SKIP_BUTTONS),
    })


def session(number, steps):
    rng = random.Random(number)
    cfg = random_config(rng)
    print(json.dumps({"session": number, "cfg": cfg}))
    ctrl = app.Controller(cfg)
    painter = app.Painter()
    t = 100000
    for step in range(steps):
        t += rng.choice(GAPS_MS)
        now = t / 1000
        event = rng.choice(EVENTS)
        if event is None:
            ctrl.update(now)
        elif isinstance(event, int):
            ctrl.handle(app.Wheel(event, now, False), now)
        else:
            ctrl.handle(event, now)
        elements = app.render(ctrl, now)
        refresh, forget = rng.random() < 0.2, rng.random() < 0.05
        if forget:
            painter.forget()
        visible, wipes = painter.plan(elements, refresh=refresh)
        painter.sent(visible + wipes)
        w = ctrl.workout
        print(json.dumps({
            "t": t, "event": event, "refresh": refresh, "forget": forget,
            "screen": ctrl.screen, "field": ctrl.field, "part": ctrl.part, "choice": ctrl.choice,
            "page": ctrl.recap_page(now) if ctrl.screen == app.RECAP else None,
            "stop_until": ctrl.stop_until, "save_due": ctrl.save_due, "cfg": ctrl.cfg,
            "sounds": ctrl.sounds, "by_itself": app.changes_by_itself(ctrl),
            "workout": w and {"phase": w.phase, "round": w.round, "paused": w.paused,
                              "work": w.stats.work_seconds, "rest": w.stats.rest_seconds,
                              "done": w.stats.rounds_completed, "stopped": w.stopped},
            # Blanks are compared once, by the first step of each session.
            "elements": elements if step == 0 else [e for e in elements if not app.is_blank(e)],
            "visible": [e["id"] for e in visible], "wipes": [e["id"] for e in wipes],
        }))
        ctrl.sounds.clear()
        if ctrl.save_due:
            ctrl.saved()


def tables():
    time_values = list(range(1, 130)) + [599, 600, 601, 3539, 3540, 3541, 3595, 3599]
    print(json.dumps({"steps": [
        [fn, v, d, s, getattr(app, fn)(v, d, s)]
        for fn in ("step_minutes", "step_seconds") for v in time_values
        for d in (1, -1) for s in app.STEPS]}))
    print(json.dumps({"rounds": [[v, d, app.step_rounds(v, d)]
                                 for v in list(range(1, 100)) + [None] for d in (1, -1)]}))
    print(json.dumps({"times": [[v, p, h, app.fmt_time(v, plus=p, hours=h)]
                                for v in (0, 1, 59, 60, 61, 599.9, 3599, 3600, 3661, 36005, 359999)
                                for p in (False, True) for h in (False, True)]}))
    printable = "".join(chr(c) for c in range(32, 127))
    print(json.dumps({"widths": [[font, app.text_width(printable, font)] for font in app.ADVANCE]}))
    raw_configs = [
        None, 3, [], "x", {}, {"last_type": "fix_rest"}, {"last_type": "nope"}, {"last_type": 5},
        {"types": 3}, {"types": {"tabata": 3}}, {"types": {"tabata": {"work": 0, "rest": 3600, "rounds": 0}}},
        {"types": {"tabata": {"work": 1, "rest": 3599, "rounds": None}}},
        {"types": {"tabata": {"work": True, "rest": "9", "rounds": 100}}},
        {"types": {"fix_work": {"work": 7.5, "rounds": 99}}},
        {"get_ready": 0}, {"get_ready": 15}, {"get_ready": 16}, {"get_ready": -1}, {"get_ready": True},
        {"sound": False}, {"sound": 0}, {"sound": "off"}, {"step": 1}, {"step": 15}, {"step": 2}, {"step": True},
        {"skip_with": "start"}, {"skip_with": "back"},
    ]
    print(json.dumps({"configs": [[raw, app.clean_config(raw)] for raw in raw_configs]}))


if __name__ == "__main__":
    tables()
    sessions, steps = int(sys.argv[1]), int(sys.argv[2])
    for number in range(sessions):
        session(number, steps)
