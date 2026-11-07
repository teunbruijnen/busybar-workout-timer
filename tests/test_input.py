"""Input: protobuf decoding of status frames, a held message (presses and
detents in order) through the controller, and the WebSocket listener against
a small local server."""
import base64
import copy
import hashlib
import itertools
import json
import os
import random
import socket
import struct
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import tearDownModule  # noqa: E402,F401  (first: guards the real settings)
from support import (BlinkChecks, Hand, bar_message, button, field_message,  # noqa: E402
                     field_varint, line_of, secs, spot, state_frame, to_summary, varint, wheel)
import app  # noqa: E402
from app import (FIX_REST, MENU, MINUTES, RECAP, RUN, SECONDS, SETTINGS,  # noqa: E402
                 SETTINGS_FIELDS, TABATA, TYPES, Wheel)


class DecodeTest(unittest.TestCase):
    def test_button_presses(self):
        for name in ("ok", "back", "start"):
            with self.subTest(name):
                self.assertEqual(app.decode_input(button(name)), [name])

    def test_releases(self):
        for name in ("ok", "back", "start"):
            self.assertEqual(app.decode_input(button(name, release=True)), [("release", name)])

    def test_ok_press_is_an_empty_message(self):
        self.assertEqual(button("ok"), bytes([0x12, 0x04, 0x5A, 0x02, 0x0A, 0x00]))

    def test_wheel(self):
        for delta in (1, -1, 3, -7, 300):
            self.assertEqual(app.decode_input(wheel(delta)), [app.Wheel(delta, None, False)])
        self.assertEqual(app.decode_input(wheel(0)), [])

    def test_wheel_carries_the_bars_clock(self):
        # State.timestamp: ms since the epoch, as firmware 1.2.4 sends it.
        self.assertEqual(app.decode_input(wheel(2, stamp_ms=1791119372191)),
                         [app.Wheel(2, 1791119372.191, False)])

    def test_a_held_burst_is_added_up_and_marked(self):
        # Several encoder events in one frame: the bar held them back.
        def encoder(delta):
            return field_message(2, field_message(11, field_message(
                3, field_varint(1, ((delta << 1) ^ (delta >> 31)) & 0xFFFFFFFF))))
        stamp = varint(1 << 3 | 1) + struct.pack("<Q", 5118)
        frame = stamp + b"".join(encoder(d) for d in (1, 1, 1, -1, 1))
        self.assertEqual(app.decode_input(frame), [app.Wheel(3, 5.118, True)])

    def test_a_held_message_keeps_its_presses_and_detents_in_order(self):
        # The bar holds presses back too: a press ends a run of detents, so
        # one turned after OK is not added to the turn before it.
        at = 5.118
        self.assertEqual(app.decode_input(wheel(1, stamp_ms=5118) + button("ok") + wheel(1)),
                         [app.Wheel(1, at, True), "ok", app.Wheel(1, at, True)])
        self.assertEqual(app.decode_input(wheel(1, stamp_ms=5118) + button("back") + wheel(-1)),
                         [app.Wheel(1, at, True), "back", app.Wheel(-1, at, True)])
        self.assertEqual(app.decode_input(wheel(1, stamp_ms=5118) + button("ok", release=True)
                                          + wheel(1)),
                         [app.Wheel(1, at, True), ("release", "ok"), app.Wheel(1, at, True)])

    def test_detents_add_up_between_presses_only(self):
        frame = wheel(1, stamp_ms=5118) + wheel(-1) + button("ok") + wheel(1) + wheel(1)
        self.assertEqual(app.decode_input(frame), ["ok", app.Wheel(2, 5.118, True)])
        frame = wheel(1, stamp_ms=5118) + wheel(1) + wheel(1)
        self.assertEqual(app.decode_input(frame), [app.Wheel(3, 5.118, True)])

    def test_other_updates_and_switches_are_ignored(self):
        switch = state_frame(2, field_varint(1, 1))
        other = field_message(2, field_message(4, b"\x08\x01"))
        self.assertEqual(app.decode_input(switch + other + field_varint(1, 7)), [])

    def test_several_updates_in_one_frame(self):
        self.assertEqual(app.decode_input(button("start") + wheel(2)),
                         ["start", app.Wheel(2, None, False)])

    def test_a_truncated_timestamp_raises_value_error(self):
        with self.assertRaises(ValueError):
            app.decode_input(b"\x09\x01\x02\x03")

    def test_truncated_frames_raise_value_error(self):
        frame = wheel(5)
        for cut in range(1, len(frame)):
            with self.subTest(cut=cut):
                with self.assertRaises(ValueError):
                    app.decode_input(frame[:cut])


class HeldMessageTest(unittest.TestCase):
    """A message the bar held back, decoded and handed to the controller on
    WORK's minutes (0:20)."""

    def work_after(self, events):
        c = app.Controller(app.default_config())
        c.handle("ok", 0.0)
        for event in events:
            c.handle(event, 1.0)
        return app.fmt_time(c.cfg["types"][app.TABATA]["work"]), c.part

    def test_turn_ok_turn_sets_the_minutes_then_the_seconds(self):
        frame = wheel(1, stamp_ms=5118) + button("ok") + wheel(1)
        self.assertEqual(self.work_after(app.decode_input(frame)), ("1:25", app.SECONDS))

    def test_a_turn_back_after_ok_is_no_bounce(self):
        # Both turns carry the message's timestamp, 0 ms apart. OK ends the
        # turn before it, so the second counts even if neither were held.
        frame = wheel(1, stamp_ms=5118) + button("ok") + wheel(-1)
        self.assertEqual(self.work_after(app.decode_input(frame)), ("1:15", app.SECONDS))
        unheld = [app.Wheel(1, 5.118, False), "ok", app.Wheel(-1, 5.118, False)]
        self.assertEqual(self.work_after(unheld), ("1:15", app.SECONDS))


# --- a held message, decoded in order ----------------------------------------

# The bar holds presses back too: decode_input keeps a held message's presses
# and detents in order. Checked against its rules written out (decode_by_the_rules),
# then through the Controller against a model: the same events turned live,
# each run of detents by its net count.

def is_detent(e):
    return isinstance(e, int) and e != 0


def is_button(e):
    return isinstance(e, str) or (isinstance(e, tuple) and e[0] == "release")


def decode_by_the_rules(events, at):
    """The four rules: each run of detents
    between presses or releases is one Wheel; a run that nets to 0 is
    dropped; held means the whole message carried more than one detent;
    every Wheel carries the message's timestamp."""
    held = sum(1 for e in events if is_detent(e)) > 1
    out, run = [], 0
    for e in events:
        if is_detent(e):
            run += e
        elif is_button(e):
            if run:
                out.append(Wheel(run, at, held))
            run = 0
            out.append(e)
    if run:
        out.append(Wheel(run, at, held))
    return out


STAMP = 1791119372191                 # ms since the epoch, as firmware 1.2.4 sends it
AT = STAMP / 1000.0


def held_wheel(d):
    return Wheel(d, AT, True)


class HeldMessageDecodeTest(unittest.TestCase):
    def decode(self, events, **kw):
        return app.decode_input(bar_message(events, stamp_ms=STAMP, **kw))

    def test_every_order_up_to_five_events(self):
        alphabet = (1, -1, "ok", "back", ("release", "start"))
        for n in range(1, 6):
            for events in itertools.product(alphabet, repeat=n):
                events = list(events)
                self.assertEqual(self.decode(events), decode_by_the_rules(events, AT), events)

    def test_mixed_orders(self):
        W = held_wheel
        cases = [
            ([1, 1, "ok"], [W(2), "ok"]),
            (["ok", -1, -1], ["ok", W(-2)]),
            ([1, "ok", 1], [W(1), "ok", W(1)]),
            ([1, "ok", ("release", "ok"), 1], [W(1), "ok", ("release", "ok"), W(1)]),
            ([-1, "back", 1, ("release", "back"), 1, 1],
             [W(-1), "back", W(1), ("release", "back"), W(2)]),
            ([1, "start", 1, "ok", 1, "back", 1], [W(1), "start", W(1), "ok", W(1), "back", W(1)]),
            ([1, 1, 1, "back", "back", -1, -1], [W(3), "back", "back", W(-2)]),
            # A bounce cancels within its run only.
            ([1, -1, 1], [W(1)]),
            ([1, 1, -1, 1, 1], [W(3)]),
            ([1, 1, -1, "ok", -1, 1, -1], [W(1), "ok", W(-1)]),
            ([1, ("release", "ok"), -1], [W(1), ("release", "ok"), W(-1)]),
            # A run that nets to 0 is dropped, on either side of a press.
            ([1, -1], []),
            ([1, -1, "ok", -1, 1], ["ok"]),
            ([1, -1, "back", 1], ["back", W(1)]),
            ([1, "back", 1, -1], [W(1), "back"]),
            ([1, -1, ("release", "ok"), 1, -1, "start", 2], [("release", "ok"), "start", W(2)]),
        ]
        for events, want in cases:
            with self.subTest(events=events):
                self.assertEqual(self.decode(events), want)

    def test_only_presses(self):
        events = ["ok", ("release", "ok"), "back", ("release", "back"), "start",
                  ("release", "start"), "ok"]
        self.assertEqual(self.decode(events), events)
        self.assertEqual(self.decode([]), [])

    def test_held_is_the_whole_message(self):
        self.assertEqual(self.decode([1]), [Wheel(1, AT, False)])
        self.assertEqual(self.decode([1, "ok"]), [Wheel(1, AT, False), "ok"])
        self.assertEqual(self.decode(["ok", -1, ("release", "ok")]),
                         ["ok", Wheel(-1, AT, False), ("release", "ok")])
        self.assertEqual(self.decode([1, "ok", -1]), [held_wheel(1), "ok", held_wheel(-1)])
        self.assertEqual(self.decode([1, -1, "ok", 1]), ["ok", held_wheel(1)])
        self.assertEqual(self.decode([3]), [Wheel(3, AT, False)])   # one encoder event

    def test_every_wheel_carries_the_message_s_timestamp(self):
        events = [1, "ok", -1, -1, ("release", "ok"), 1, "back", 1]
        for stamp_last in (False, True):
            got = self.decode(events, stamp_last=stamp_last)
            self.assertEqual([w.at for w in got if isinstance(w, Wheel)], [AT] * 4)
        got = app.decode_input(bar_message(events))           # the emulator: no clock
        self.assertEqual([w.at for w in got if isinstance(w, Wheel)], [None] * 4)

    def test_what_doesnt_end_a_run(self):
        # The switch and a zero delta are neither presses nor releases.
        self.assertEqual(self.decode([1, ("switch", 3), 1]), [held_wheel(2)])
        self.assertEqual(self.decode([1, 0, 1]), [held_wheel(2)])
        self.assertEqual(self.decode([0, 1, 0]), [Wheel(1, AT, False)])   # 0 is no detent


def runs_of(events):
    """Presses and releases as they are; each run of detents as its net
    count (a run that nets to 0 kept as 0)."""
    out, run = [], None
    for e in events:
        if is_detent(e):
            run = (run or 0) + e
        elif is_button(e):
            if run is not None:
                out.append(run)
            run = None
            out.append(e)
    if run is not None:
        out.append(run)
    return out


def deliver_held(h, events, gap=0.3, bar_gap=1.0):
    """The message as the bar sends it: decoded, then handled at one moment."""
    h.now += gap
    h.bar += bar_gap
    got = app.decode_input(bar_message(events, stamp_ms=round(h.bar * 1000)))
    for e in got:
        h.c.handle(e, h.now)
    return got


def deliver_live(h, events, gap=0.3, bar_gap=1.0, spacing=0.09, same_stamp=False):
    """The model: the same events delivered live, one per message, at the same
    moment on the local clock, except that each run of detents is its net
    count (its bounces cancel). The single detents lie `spacing` apart on the
    bar's clock, the last at the message's stamp (no bounces between them),
    or all at the stamp with `same_stamp`. On the recap, a run of more than
    HELD_MAX in a message of more than one detent is dropped: the per-run
    flick rule."""
    h.now += gap
    h.bar += bar_gap
    held = sum(1 for e in events if is_detent(e)) > 1
    runs = runs_of(events)
    n = sum(abs(r) for r in runs if isinstance(r, int))
    t = h.bar - (0 if same_stamp else spacing * max(0, n - 1))
    for r in runs:
        if not isinstance(r, int):
            h.c.handle(r, h.now)
            continue
        if h.c.screen == RECAP and held and abs(r) > app.HELD_MAX:
            t += 0 if same_stamp else spacing * abs(r)
            continue
        for _ in range(abs(r)):
            h.c.handle(Wheel(1 if r > 0 else -1, round(t, 3), False), h.now)
            t += 0 if same_stamp else spacing


def snapshot(h):
    """Everything a message can change that the user can see or that steers
    what comes next. The blink's anchor only counts in the menu: every way
    back to the menu is a press, which sets it again."""
    c, w = h.c, h.c.workout
    return {"spot": spot(c), "choice": c.choice, "cfg": copy.deepcopy(c.cfg),
            "page": c.recap_page(h.now) if c.screen == RECAP else None,
            "stop": c.stop_until,
            "workout": None if w is None else (w.phase, w.round, w.paused, w.stopped,
                                                w.stats.work_seconds, w.stats.rest_seconds),
            "blink": (c.input_at, c.after_detent) if c.screen == MENU else None,
            "save_due": c.save_due, "turning": c._last_detent[1]}


def _run(*then, kind=TABATA, skip_with="ok", wait=0.0, **kw):
    def make():
        args = dict(get_ready=3, work=5, rest=3, rounds=2)
        args.update(kw)
        h = Hand(kind=kind, skip_with=skip_with, **args)(*to_summary(kind), "start")
        if wait:
            h.wait(wait)
        return h(*then)
    return make


def _recap(*then, wait=1.5, stop=False):
    def make():
        h = Hand(get_ready=0, work=2, rest=1, rounds=1)(*to_summary(TABATA), "start")
        if stop:
            h("back", "back", gap=0.2)
        else:
            h.wait(2.0)
        h.wait(wait)
        return h(*then)
    return make


def _pending_recap():
    h = Hand(get_ready=0, work=2, rest=1, rounds=1)(*to_summary(TABATA), "start")
    h("back", gap=1.5)                                         # STOP? up
    h.wait(0.6)                                                # the WORK runs out
    assert h.c.screen == RECAP and h.c.stop_until is not None
    return h


def everywhere():
    """(name, a function that makes a Hand there) for every screen and field
    a held message can land on."""
    out = []
    values = {"work": secs("1:05"), "rest": secs("0:40"), "rounds": 3}
    for kind in TYPES:
        line = line_of(kind)
        for k, where in enumerate(line):
            out.append(("%s %r by OK" % (kind, where),
                        lambda kind=kind, k=k: Hand(kind=kind, **values)(*["ok"] * k)))
            if 0 < k < len(line) - 1:
                out.append(("%s %r by BACK" % (kind, where),
                            lambda kind=kind, k=k, line=line: Hand(kind=kind, **values)(
                                *to_summary(kind), *["back"] * (len(line) - 1 - k))))
    for i, field in enumerate(SETTINGS_FIELDS):
        out.append((field, lambda i=i: Hand(get_ready=14).choose(SETTINGS)("ok", *["ok"] * i)))
    out.append(("type on SETTINGS", lambda: Hand().choose(SETTINGS)))
    out += [("get ready", _run()), ("work", _run(wait=3.5)), ("rest", _run(wait=8.6)),
            ("paused", _run("start", wait=3.5)), ("STOP? up", _run("back", wait=3.5)),
            ("open work", _run(kind=FIX_REST, wait=4.0)),
            ("swapped buttons", _run(skip_with="start", wait=3.5)),
            ("unlimited", _run(rounds=None, wait=9.0)),
            ("recap in its grace", _recap(wait=0.0)), ("recap cycling", _recap()),
            ("recap later", _recap(wait=7.0)), ("recap paged", _recap(1)),
            ("recap stopped", _recap(stop=True)), ("recap, STOP? pending", _pending_recap)]
    return out


MESSAGES = (
    [1, "back", 1], [-1, "back", -1], [1, "back", -1], [-1, "back", 1],
    [1, 1, "back", ("release", "back"), -1], ["back", 1], [1, "back"],
    [1, "back", ("release", "back"), "back", ("release", "back"), 1],
    [1, "ok", 1], [-1, "ok", ("release", "ok"), -1, -1], [1, 1, "ok", 1, 1],
    [1, "start", -1], [1, -1, "ok", -1, 1], [1, -1, 1, "back", -1, 1, -1],
    [1, 1, 1, "ok"], [1, "ok", 1, 1, 1], [1, 1, 1, -1], [2, "back", 1],
    ["ok", ("release", "ok"), "back", ("release", "back")],
)


class HeldMessageControllerTest(BlinkChecks, unittest.TestCase):
    def compare(self, make, events, gap=0.3, same_stamp=False):
        a, b = make(), make()
        self.assertEqual(snapshot(a), snapshot(b))
        deliver_held(a, events, gap=gap)
        deliver_live(b, events, gap=gap, same_stamp=same_stamp)
        return snapshot(a), snapshot(b)

    def test_every_screen_matches_the_live_model(self):
        for name, make in everywhere():
            for events in MESSAGES:
                for gap in (0.0, 0.3, 1.2):
                    with self.subTest(where=name, events=events, gap=gap):
                        held, live = self.compare(make, events, gap=gap)
                        self.assertEqual(held, live)

    def test_random_messages_match_the_live_model(self):
        rng = random.Random(20261006)
        places = everywhere()
        alphabet = (1, 1, -1, -1, "ok", "back", "start", ("release", "ok"),
                    ("release", "back"), ("release", "start"))
        for _ in range(2000):
            name, make = rng.choice(places)
            events = [rng.choice(alphabet) for _ in range(rng.randint(1, 8))]
            gap = rng.choice((0.0, 0.3, 0.9, 2.5))
            held, live = self.compare(make, events, gap=gap)
            if held != live:
                self.fail("%s, %r, %.1f s later:\n held %r\n live %r"
                          % (name, events, gap, held, live))

    def test_turn_ok_turn_sets_the_minutes_then_the_seconds(self):
        for events, want in (([1, "ok", 1], "1:25"),
                             ([1, "ok", ("release", "ok"), 1], "1:25"),
                             ([-1, -1, "ok", -1, -1, -1], "58:05"),
                             ([1, 1, -1, "ok", 1, -1, 1], "1:25"),
                             ([1, -1, "ok", 1], "0:25"),
                             ([1, "ok", 1, -1], "1:20")):
            with self.subTest(events=events):
                h = Hand()("ok")                               # WORK 0:20, its minutes
                deliver_held(h, events)
                self.assertEqual((h.spot, h.shown("work")), (("work", SECONDS), want))

    def test_turn_ok_turn_blinks_like_the_last_event(self):
        h = Hand()("ok")
        deliver_held(h, [1, "ok", 1])
        self.assert_rhythm(h, h.now, True)                     # lit for the second
        h = Hand()("ok")
        deliver_held(h, [1, "ok", 1, -1])                      # last run nets to 0
        self.assert_rhythm(h, h.now, False)                    # the press rhythm

    def test_turn_back_turn_on_each_part(self):
        # (presses from TYPE, the message, where it lands, values after it)
        h0 = dict(work=secs("1:05"), rest=secs("0:40"), rounds=3)
        turn_back_turn = [1, "back", ("release", "back"), 1]
        cases = [
            (["ok"] * 2, turn_back_turn, ("work", MINUTES), {"work": "2:10"}),
            (["ok"] * 2, [1, "back", -1], ("work", MINUTES), {"work": "0:10"}),
            (["ok"] * 3, turn_back_turn, ("work", SECONDS), {"rest": "1:40", "work": "1:10"}),
            (["ok"] * 4, turn_back_turn, ("rest", MINUTES), {"rest": "1:45"}),
            (["ok"] * 5, turn_back_turn, ("rest", SECONDS), {"rounds": 4, "rest": "0:45"}),
            (["ok"], turn_back_turn, ("type", FIX_REST), {"work": "2:05"}),
            (to_summary(TABATA), [1, "back", 1], "rounds", {"rounds": 4}),   # summary: no turn
        ]
        for presses, events, where, want in cases:
            with self.subTest(presses=len(presses), events=events):
                h = Hand(**h0)(*presses)
                deliver_held(h, events)
                self.assertEqual(h.spot, where)
                for field, value in want.items():
                    got = h.value(field) if field == "rounds" else h.shown(field)
                    self.assertEqual(got, value, field)
        h = Hand().choose(SETTINGS)("ok")                      # GET READY 5
        deliver_held(h, [1, "back", 1])
        self.assertEqual((h.spot, h.c.cfg["get_ready"]), (("type", TABATA), 6))

    def test_turn_ok_turn_on_type_picks_the_next_type(self):
        h = Hand()
        deliver_held(h, [1, "ok", 1])
        self.assertEqual((h.spot, h.c.kind), (("rest", MINUTES), FIX_REST))
        self.assertEqual(h.shown("rest"), "2:30")

    def test_recap_pages_per_run(self):
        # HELD_MAX applies to each run, so a held
        # [+1, +1, OK, +1, +1] pages 2, then OK, then 2.
        def recap_on_work():
            h = Hand(get_ready=0, work=2, rest=1, rounds=1)(*to_summary(TABATA), "start")
            h.wait(2.0 + 1.2)                                  # 1.2 s after the end
            self.assertEqual((h.spot, h.c.recap_page(h.now)), (RECAP, "work"))
            return h
        pages = []
        turn = app.Controller._turn_page

        def spy(c, delta, now):
            turn(c, delta, now)
            pages.append(c.page)
        cases = [([1, 1, "ok", 1, 1], ["rounds", "total", "rest"]),
                 ([1, 1, 1, "ok"], ["rest"]),                    # the flick ignored
                 ([1, "ok", 1, 1, 1], ["rest", "rounds"]),       # the flick after OK ignored
                 ([1, 1, 1, -1], ["rounds"]),                    # 4 detents, net 2: pages 2
                 ([1, 1, -1, -1, "ok"], ["rest"]),
                 ([-1, -1, "ok", -1, -1], ["rounds", "total", "rest"]),
                 ([1, ("release", "ok"), 1, 1], ["rest", "total"])]
        for events, want in cases:
            with self.subTest(events=events):
                pages.clear()
                h = recap_on_work()
                with mock.patch.object(app.Controller, "_turn_page", spy):
                    deliver_held(h, events, gap=0.0)
                self.assertEqual(pages, want)

    def test_recap_grace_with_turns_around_ok(self):
        h = Hand(get_ready=0, work=2, rest=1, rounds=1)(*to_summary(TABATA), "start")
        h.wait(2.3)                                            # 0.3 s after the end
        deliver_held(h, [1, "ok", ("release", "ok"), 1, "start"], gap=0.0)
        self.assertEqual((h.spot, h.c.page), (RECAP, "rounds"))   # OK, START ignored

    def test_back_between_turns_in_a_workout(self):
        h = Hand(get_ready=0, work=20, rest=10, rounds=2)(*to_summary(TABATA), "start")
        deliver_held(h, [1, "back", 1], gap=1.0)
        self.assertEqual(h.spot, RUN)
        self.assertIsNotNone(h.c.stop_until)                   # STOP? up
        deliver_held(h, [1, "back", ("release", "back"), 1, -1, 1], gap=0.5)
        self.assertEqual((h.spot, h.c.recap_page(h.now)), (RECAP, "rest"))   # paged once
        self.assertTrue(h.c.workout.stopped)

    def test_a_pending_stop_back_then_a_turn_on_the_recap(self):
        h = _pending_recap()
        deliver_held(h, [1, "back", ("release", "back"), 1], gap=0.1)
        self.assertEqual((h.spot, h.c.page), (RECAP, "rounds"))   # BACK ignored once
        deliver_held(h, ["back", -1], gap=0.3)
        self.assertEqual((h.spot, h.c.kind), (("type", SETTINGS), TABATA))

    # -- the 80 ms bounce rule --

    def test_two_runs_split_by_a_release_both_count(self):
        # Both Wheels carry the stamp (0 ms apart) and are held, so the
        # second isn't a bounce: the message moves by its net count, 0.
        # Delivered live with the same stamp, the second would be a bounce.
        for release in (("release", "ok"), ("release", "back"), ("release", "start")):
            with self.subTest(release=release):
                h = Hand()("ok")
                deliver_held(h, [1, release, -1])
                self.assertEqual(h.shown("work"), "0:20")
                live = Hand()("ok")
                deliver_live(live, [1, release, -1], same_stamp=True)
                self.assertEqual(live.shown("work"), "1:20")   # the model diverges here
                live = Hand()("ok")
                deliver_live(live, [1, release, -1])           # 90 ms apart: both count
                self.assertEqual(live.shown("work"), "0:20")

    def test_single_detents_with_the_same_stamp_in_two_messages(self):
        h = Hand()("ok")
        ms = round((h.bar + 1.0) * 1000)
        h.c.handle(app.decode_input(bar_message([1], stamp_ms=ms))[0], h.now)
        h.c.handle(app.decode_input(bar_message([-1], stamp_ms=ms))[0], h.now)
        self.assertEqual(h.shown("work"), "1:20")              # 0 ms back: a bounce
        h.c.handle(app.decode_input(bar_message([-1], stamp_ms=ms + 80))[0], h.now)
        self.assertEqual(h.shown("work"), "0:20")              # 80 ms: a turn

    def test_a_live_detent_just_after_a_held_message(self):
        # A bounce is measured against the direction of the last Wheel: a
        # run's net direction, as the model has it (a held burst moves by
        # its net count), not that of its last single detent.
        for events, back, want in (([1, "ok", 1, 1], -1, "1:30"),      # bounce
                                   ([1, "ok", -1, -1], 1, "1:10"),     # bounce
                                   ([1, "ok", 1, -1], -1, "1:15"),     # net 0: no turn yet
                                   ([1, "ok", -1, -1, -1, 1, 1], 1, "1:15")):   # net -1
            with self.subTest(events=events):
                h = Hand()("ok")                               # WORK 0:20, its minutes
                deliver_held(h, events)
                self.assertEqual(h.spot, ("work", SECONDS))
                h.c.handle(Wheel(back, h.bar + 0.05, False), h.now + 0.05)
                self.assertEqual(h.shown("work"), want)

    def test_a_held_message_with_one_detent_keeps_the_bounce_rule(self):
        h = Hand()("ok")
        h(1)                                                   # live +1
        bar = h.bar
        got = app.decode_input(bar_message([("release", "ok"), -1],
                                           stamp_ms=round((bar + 0.05) * 1000)))
        self.assertEqual(got[1], Wheel(-1, round(bar + 0.05, 3), False))
        for e in got:
            h.c.handle(e, h.now + 0.05)
        self.assertEqual(h.shown("work"), "1:20")              # a bounce, as live

    def test_sound_flips_by_the_net_count_not_detent_by_detent(self):
        # A held burst moves by its net count, so two detents leave SOUND as
        # it was, and no tick. Turned
        # live, they would flip it twice and tick once on the way.
        h = Hand().choose(SETTINGS)("ok", "ok")                # SOUND
        h.c.cfg["sound"] = False
        deliver_held(h, [1, 1, "ok", -1])
        self.assertEqual((h.spot, h.c.cfg["sound"], h.c.sounds), ("step", False, []))


# --- the listener ------------------------------------------------------------

class FakeStatusWs(threading.Thread):
    """Accepts one WebSocket client, checks its {"enable": true}, then sends
    a ping and the given binary frames (the last one in two fragments)."""

    def __init__(self, frames):
        super().__init__(daemon=True)
        self.frames = frames
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.request = None
        self.enable = None
        self.pong = None

    def run(self):
        conn, _ = self.server.accept()
        with conn:
            stream = conn.makefile("rb")
            lines = []
            while True:
                line = stream.readline()
                if line in (b"\r\n", b""):
                    break
                lines.append(line.decode().strip())
            self.request = lines[0]
            key = next(v.split(": ")[1] for v in lines if v.lower().startswith("sec-websocket-key"))
            accept = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                          "Connection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n"
                          % accept).encode())
            _, _, body = app.InputListener._read_frame(stream)
            self.enable = json.loads(body)
            conn.sendall(bytes([0x89, 2]) + b"hi")                     # ping
            _, opcode, self.pong = app.InputListener._read_frame(stream)
            *whole, last = self.frames
            for frame in whole:
                conn.sendall(bytes([0x82, len(frame)]) + frame)
            half = len(last) // 2
            conn.sendall(bytes([0x02, half]) + last[:half])              # not FIN
            conn.sendall(bytes([0x80, len(last) - half]) + last[half:])  # continuation
            time.sleep(0.5)
        self.server.close()


class HangUpServer(threading.Thread):
    """Completes the WebSocket handshake, takes {"enable": true}, then hangs
    up; again for every connection. Counts them."""

    def __init__(self):
        super().__init__(daemon=True)
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(5)
        self.server.settimeout(0.2)
        self.port = self.server.getsockname()[1]
        self.connections = 0
        self.done = threading.Event()

    def run(self):
        while not self.done.is_set():
            try:
                conn, _ = self.server.accept()
            except socket.timeout:
                continue
            with conn:
                stream = conn.makefile("rb")
                lines = []
                while True:
                    line = stream.readline()
                    if line in (b"\r\n", b""):
                        break
                    lines.append(line.decode())
                key = next(v.split(": ")[1].strip() for v in lines
                           if v.lower().startswith("sec-websocket-key"))
                accept = base64.b64encode(hashlib.sha1(
                    (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
                conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                              "Connection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n"
                              % accept).encode())
                app.InputListener._read_frame(stream)
                self.connections += 1
                stream.close()                    # or the socket stays open
                conn.shutdown(socket.SHUT_RDWR)
        self.server.close()


class ListenerTest(unittest.TestCase):
    def test_a_dropped_connection_comes_back_at_once(self):
        # Once a session has connected, losing it doesn't grow the wait
        # before the next try.
        server = HangUpServer()
        server.start()
        logged = []
        listener = app.InputListener("127.0.0.1:%d" % server.port, log=logged.append)
        listener.start()
        time.sleep(2.0)
        listener.stop()
        server.done.set()
        server.join(3)
        self.assertGreaterEqual(server.connections, 5)

    def test_events_arrive_in_order(self):
        server = FakeStatusWs([button("ok"), button("ok", release=True), wheel(-2),
                               button("back")])
        server.start()
        logged = []
        listener = app.InputListener("127.0.0.1:%d" % server.port, token="s3cret",
                                     log=logged.append)
        listener.start()
        events, deadline = [], time.monotonic() + 3
        while len(events) < 4 and time.monotonic() < deadline:
            listener.wait(0.1)
            events += listener.poll()
        listener.stop()
        server.join(3)
        turned = events[2]
        self.assertEqual(events[:2] + events[3:], ["ok", ("release", "ok"), "back"])
        self.assertEqual((turned.delta, turned.held), (-2, False))
        self.assertAlmostEqual(turned.at, time.time(), delta=5)  # no bar clock: arrival
        self.assertEqual(server.enable, {"enable": True})
        self.assertEqual(server.pong, b"hi")
        self.assertEqual(server.request, "GET /api/status/ws?x-api-token=s3cret HTTP/1.1")

    def test_no_server_is_reported_once(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()                                   # nothing listens there
        logged = []
        listener = app.InputListener("127.0.0.1:%d" % port, log=logged.append)
        listener.start()
        time.sleep(0.3)
        listener.stop()
        self.assertEqual(len(logged), 1)
        self.assertIn("no button input", logged[0])


if __name__ == "__main__":
    unittest.main()
