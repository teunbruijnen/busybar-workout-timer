"""The menu: WORK and REST set in two parts, minutes then seconds, the walk
with OK and BACK, the blink, START in the menu, and BACK in SETTINGS
(SPEC 2, 3, 4 and 6).

The wheel is checked against models written from SPEC 2's words
(one detent at a time, and a closed form for whole bursts), the walk
against SPEC 4's order read as one line of parts (support.line_of), and the
blink against SPEC 6's rhythm (support.spec_hidden). The SPEC's examples are
checked literally, and a seeded random walk mixes it all."""
import copy
import itertools
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import tearDownModule  # noqa: E402,F401  (first: guards the real settings)
from support import (BAR0, LIT_AFTER_DETENT, LIT_AFTER_PRESS, OFF, T0,  # noqa: E402
                     BlinkChecks, Hand, Held, clock_parts, hidden, line_of, mmss, secs,
                     spec_hidden, to_summary)
import app  # noqa: E402
from app import (FIX_REST, FIX_WORK, MENU, MINUTES, RECAP, RUN, SECONDS,  # noqa: E402
                 SETTINGS, SETTINGS_FIELDS, STEPS, SUMMARY, TABATA, TIME_FIELDS,
                 TYPE_FIELDS, TYPES, Wheel)


# --- the SPEC as models ------------------------------------------------------

def spec_minute(value, way, step):
    """SPEC 2, one detent on the minutes: 0-59, wrapping; landing on 0 with
    the seconds below the step sets them to the step."""
    m, s = divmod(value, 60)
    m = (m + way) % 60
    if m == 0 and s < step:
        s = step
    return m * 60 + s


def spec_minutes_burst(value, delta, step):
    """The same for a whole burst, in closed form: the minutes move by
    `delta` mod 60, and the seconds rise to the step if the burst lands on
    0 at any detent: up past 59, down to 0 from 1 or above, or any lap of
    60 or more (it meets every minute)."""
    m, s = divmod(value, 60)
    lands = (abs(delta) >= 60 or (delta > 0 and m + delta >= 60)
             or (delta < 0 and 1 <= m <= -delta))
    return (m + delta) % 60 * 60 + (max(s, step) if lands else s)


def spec_second(value, way, step):
    """SPEC 2, one detent on the seconds: multiples of the step up to 60
    minus the step, from the step at 0 minutes; they wrap within the
    minute; a value off the ladder snaps onto it, and one below the lowest
    (0:03 with 5 s) goes up to it in either direction."""
    m, s = divmod(value, 60)
    ladder = list(range(step if m == 0 else 0, 60 - step + 1, step))
    if way > 0:
        higher = [x for x in ladder if x > s]
        s = higher[0] if higher else ladder[0]
    elif s < ladder[0]:
        s = ladder[0]
    else:
        lower = [x for x in ladder if x < s]
        s = lower[-1] if lower else ladder[-1]
    return m * 60 + s


def spec_turn(detent, value, delta, step):
    for _ in range(abs(delta)):
        value = detent(value, 1 if delta > 0 else -1, step)
    return value


ROUNDS_CYCLE = list(range(1, 100)) + [None]


def spec_rounds(value, delta):
    return ROUNDS_CYCLE[(ROUNDS_CYCLE.index(value) + delta) % len(ROUNDS_CYCLE)]


BUTTONS = ("ok", "back", "start")


# --- the SPEC's examples, literally ------------------------------------------

class SpecExamplesTest(unittest.TestCase):
    def test_seconds_wrap_within_the_minute_1_50_1_55_1_00_1_05_and_back(self):
        h = Hand(work=secs("1:50"))("ok", "ok")
        self.assertEqual(h.spot, ("work", SECONDS))
        self.assertEqual(h.turns(1, 3), ["1:55", "1:00", "1:05"])
        self.assertEqual(h.turns(-1, 3), ["1:00", "1:55", "1:50"])

    def test_0_05_and_0_55_wrap_into_each_other_at_0_minutes(self):
        h = Hand(work=secs("0:05"))("ok", "ok")
        self.assertEqual(h.turns(-1, 1), ["0:55"])
        self.assertEqual(h.turns(1, 1), ["0:05"])
        self.assertEqual(h.turns(-1, 2), ["0:55", "0:50"])

    def test_1_00_goes_to_0_05_when_the_minutes_go_down(self):
        h = Hand(work=secs("1:00"))("ok")
        self.assertEqual(h.spot, ("work", MINUTES))
        self.assertEqual(h.turns(-1, 2), ["0:05", "59:05"])
        self.assertEqual(h.turns(1, 2), ["0:05", "1:05"])  # the minutes never touch :05 again

    def test_the_highest_time_for_each_step(self):
        for step, highest in ((1, "59:59"), (5, "59:55"), (10, "59:50"), (15, "59:45")):
            with self.subTest(step=step):
                h = Hand(step=step)("ok")                      # WORK 0:20, its minutes
                h.turns(1, 59, gap=0.01)                       # fast: still one per detent
                self.assertEqual(h.shown(), "59:20")
                h("ok")
                lap = h.turns(1, 60 // step + 1)
                self.assertEqual(max(lap, key=secs), highest)
                after = lap[lap.index(highest) + 1]
                self.assertEqual(after, "59:00")               # wraps within the minute
                h("back")                                      # the minutes, at their top
                seconds = h.shown()[-2:]
                self.assertEqual(h.turns(1, 2), ["0:" + seconds, "1:" + seconds])
                h = Hand(step=step, work=secs("59:00"))("ok", "ok")
                self.assertEqual(h.turns(-1, 1), [highest])    # and back the other way

    def test_a_saved_0_03_seen_with_a_5_s_step_goes_to_0_05_either_way(self):
        # Set 0:03 with a 1 s step on the bar, switch STEP to 5 s, come back.
        for way in (1, -1):
            with self.subTest(way=way):
                h = Hand(step=1)("ok", "ok")                   # WORK's seconds, 0:20
                h(*[-1] * 17)
                self.assertEqual(h.shown(), "0:03")
                h("back", "back").choose(SETTINGS)("ok", "ok", "ok", 1, "ok", "ok")
                self.assertEqual((h.spot, h.c.cfg["step"]), (("type", TABATA), 5))
                h("ok")
                self.assertEqual((h.spot, h.shown()), (("work", MINUTES), "0:03"))
                h("ok")
                self.assertEqual(h.shown(), "0:03")            # stays until turned
                self.assertEqual(h.turns(way, 1), ["0:05"])


# --- the seconds -------------------------------------------------------------

class SecondsTest(unittest.TestCase):
    def test_step_seconds_matches_the_spec_for_every_time_step_and_burst(self):
        # Every second of the minutes that matter (0, and some others: the
        # seconds don't depend on which; test_turned_seconds_... runs them all).
        values = [m * 60 + s for m in (0, 1, 2, 9, 10, 30, 58, 59) for s in range(60)][1:]
        for step in STEPS:
            lap = 60 // step                    # detents in a lap of the seconds above 0:59
            deltas = sorted({1, 2, 3, lap - 1, lap, lap + 1, 2 * lap + 3})
            for value in values:
                for d in deltas + [-d for d in deltas]:
                    want = spec_turn(spec_second, value, d, step)
                    got = app.step_seconds(value, d, step)
                    if got != want:
                        self.fail("step %d: %s %+d -> %s, SPEC %s"
                                  % (step, mmss(value), d, mmss(got), mmss(want)))

    def test_a_burst_moves_like_its_detents_one_by_one(self):
        for step in STEPS:
            for value in list(range(1, 125)) + list(range(3480, 3600)):
                for d in (2, 5, 13, -2, -5, -13):
                    one_by_one = value
                    for _ in range(abs(d)):
                        one_by_one = app.step_seconds(one_by_one, 1 if d > 0 else -1, step)
                    self.assertEqual(app.step_seconds(value, d, step), one_by_one,
                                     (step, mmss(value), d))

    def test_a_full_lap_at_0_and_at_1_minute_for_every_step(self):
        for step in STEPS:
            with self.subTest(step=step):
                at0 = ["0:%02d" % s for s in range(step, 60, step)]
                at1 = ["1:%02d" % s for s in range(0, 60, step)]
                h = Hand(step=step, work=step)("ok", "ok")     # 0:<step>, the lowest
                self.assertEqual(h.turns(1, len(at0)), at0[1:] + at0[:1])
                self.assertEqual(h.turns(-1, len(at0)), at0[::-1])
                h = Hand(step=step, work=60)("ok", "ok")       # 1:00
                self.assertEqual(h.turns(1, len(at1)), at1[1:] + at1[:1])
                self.assertEqual(h.turns(-1, len(at1)), at1[::-1])

    def test_saved_odd_values_on_their_first_detent(self):
        # (saved, step, after one detent up, after one detent down)
        cases = [("0:03", 5, "0:05", "0:05"), ("0:03", 10, "0:10", "0:10"),
                 ("0:03", 15, "0:15", "0:15"), ("0:01", 15, "0:15", "0:15"),
                 ("0:58", 5, "0:05", "0:55"), ("0:58", 10, "0:10", "0:50"),
                 ("0:58", 15, "0:15", "0:45"), ("0:58", 1, "0:59", "0:57"),
                 ("0:59", 1, "0:01", "0:58"),
                 ("59:59", 5, "59:00", "59:55"), ("59:59", 10, "59:00", "59:50"),
                 ("59:59", 15, "59:00", "59:45"), ("59:59", 1, "59:00", "59:58"),
                 ("1:03", 5, "1:05", "1:00"), ("1:58", 15, "1:00", "1:45"),
                 ("0:20", 15, "0:30", "0:15"), ("0:17", 15, "0:30", "0:15"),
                 ("0:01", 1, "0:02", "0:59")]
        for saved, step, up, down in cases:
            for field in TIME_FIELDS:
                with self.subTest(saved=saved, step=step, field=field):
                    h = Hand(step=step, **{field: secs(saved)})
                    h("ok", *(["ok", "ok"] if field == "rest" else []), "ok")
                    self.assertEqual((h.spot, h.shown()), ((field, SECONDS), saved))
                    self.assertEqual(h.turns(1, 1), [up])
                    h = Hand(step=step, **{field: secs(saved)})
                    h("ok", *(["ok", "ok"] if field == "rest" else []), "ok")
                    self.assertEqual(h.turns(-1, 1), [down])

    def test_turned_seconds_are_always_a_valid_time(self):
        for step in STEPS:
            for value in range(app.TIME_MIN, app.TIME_MAX + 1):
                for d in (1, -1, 7, -7):
                    m, s = divmod(app.step_seconds(value, d, step), 60)
                    self.assertEqual(m, value // 60)                  # minutes stay
                    self.assertEqual(s % step, 0, (step, value, d))   # snapped
                    self.assertLessEqual(s, 60 - step)
                    self.assertGreaterEqual(m * 60 + s, step)          # never below the step

    def test_bursts_across_the_wrap(self):
        for start, delta, want in (("0:50", 3, "0:10"), ("1:50", 3, "1:05"),
                                   ("0:10", -3, "0:50"), ("1:05", -3, "1:50"),
                                   ("0:05", -12, "0:55"), ("0:55", 23, "0:05"),
                                   ("1:00", -13, "1:55"), ("0:15", -4, "0:50")):
            for held in (False, True):
                with self.subTest(start=start, delta=delta, held=held):
                    h = Hand(work=secs(start))("ok", "ok")
                    h(Held(delta) if held else delta)
                    self.assertEqual(h.shown(), want)


# --- the minutes, and their wrap 59 <-> 0 ------------------------------------

class MinutesTest(unittest.TestCase):
    def test_step_minutes_matches_the_spec_for_every_time_step_and_burst(self):
        for step in STEPS:
            for value in range(app.TIME_MIN, app.TIME_MAX + 1):
                for d in (1, 2, 59, 70, -1, -2, -59, -70):
                    want = spec_turn(spec_minute, value, d, step)
                    got = app.step_minutes(value, d, step)
                    if got != want:
                        self.fail("step %d: %s %+d -> %s, SPEC %s"
                                  % (step, mmss(value), d, mmss(got), mmss(want)))

    def test_down_to_0_with_the_seconds_below_the_step_sets_them_to_the_step(self):
        for step in STEPS:
            with self.subTest(step=step):
                h = Hand(step=step, work=60)("ok")
                self.assertEqual(h.turns(-1, 1), ["0:%02d" % step])
                h = Hand(step=step, work=180)("ok", Held(-3))   # 3:00, a held burst
                self.assertEqual(h.shown(), "0:%02d" % step)
        for saved, step, want in (("1:03", 5, "0:05"), ("1:03", 1, "0:03"),
                                  ("1:14", 15, "0:15"), ("1:20", 15, "0:20"),
                                  ("1:58", 5, "0:58"), ("2:00", 1, "0:01")):
            with self.subTest(saved=saved, step=step):
                h = Hand(step=step, work=secs(saved))("ok", Held(-(secs(saved) // 60)))
                self.assertEqual(h.shown(), want)

    def test_wrapped_at_0_and_59_with_odd_seconds(self):
        for saved, step, way, want in (
                ("0:03", 5, -1, ["59:03", "58:03", "57:03"]),
                ("0:58", 5, -1, ["59:58", "58:58", "57:58"]),
                ("0:01", 15, -1, ["59:01", "58:01", "57:01"]),
                ("59:59", 5, 1, ["0:59", "1:59", "2:59"]),
                ("59:03", 15, 1, ["0:15", "1:15", "2:15"]),
                ("58:58", 5, 1, ["59:58", "0:58", "1:58"]),
                ("58:03", 5, 1, ["59:03", "0:05", "1:05"]),
                ("1:03", 5, -1, ["0:05", "59:05", "58:05"])):
            with self.subTest(saved=saved, step=step):
                h = Hand(step=step, work=secs(saved))("ok")
                self.assertEqual(h.turns(way, 3), want)
                h = Hand(step=step, work=secs(saved))("ok", Held(way * 3))
                self.assertEqual(h.shown(), want[-1])

    def test_the_minutes_leave_the_seconds_alone_otherwise(self):
        for saved, way, want in (("0:03", 1, "1:03"), ("0:58", 1, "1:58"),
                                 ("12:47", -1, "11:47"), ("1:58", -1, "0:58")):
            with self.subTest(saved=saved):
                h = Hand(step=15, work=secs(saved))("ok")
                self.assertEqual(h.turns(way, 1), [want])


ODD = (secs("0:03"), secs("0:58"), secs("59:59"), secs("59:03"))
SOME_SECONDS = (0, 1, 2, 3, 4, 5, 6, 9, 10, 11, 14, 15, 16, 29, 30, 44, 45, 46, 54, 55,
                58, 59)
SOME_VALUES = [m * 60 + s for m in range(60) for s in SOME_SECONDS if m or s]
BURSTS = (1, 2, 3, 58, 59, 60, 61, 62, 119, 120, 121)


class MinutesWrapTest(unittest.TestCase):
    def test_a_burst_is_its_detents_one_by_one_and_the_closed_form(self):
        for step in STEPS:
            for value in SOME_VALUES:
                for d in BURSTS + tuple(-d for d in BURSTS):
                    got = app.step_minutes(value, d, step)
                    one_by_one = spec_turn(spec_minute, value, d, step)
                    closed = spec_minutes_burst(value, d, step)
                    if not got == one_by_one == closed:
                        self.fail("step %d: %s %+d -> %s; one by one %s, closed form %s" % (
                            step, mmss(value), d, mmss(got), mmss(one_by_one), mmss(closed)))

    def test_every_burst_near_the_wrap(self):
        for step in STEPS:
            for m in (0, 1, 2, 57, 58, 59):
                for s in (0, 1, 3, step - 1, step, 30, 59):
                    value = m * 60 + s
                    if not value or s > 59:
                        continue
                    for d in range(-125, 126):
                        self.assertEqual(app.step_minutes(value, d, step),
                                         spec_minutes_burst(value, d, step),
                                         (step, mmss(value), d))

    def test_held_equals_live_through_the_controller(self):
        starts = ("0:03", "0:20", "1:00", "1:03", "2:03", "57:00", "58:03", "59:03",
                  "59:59", "0:58")
        for kind, field in ((TABATA, "work"), (TABATA, "rest"), (FIX_REST, "rest"),
                            (FIX_WORK, "work")):
            presses = ["ok"] + ["ok"] * (2 * TYPE_FIELDS[kind].index(field))
            for step in STEPS:
                for start in starts:
                    for d in (2, 3, 60, 61, 120, -2, -3, -60, -61, -120):
                        live = Hand(kind=kind, step=step, **{field: secs(start)})(*presses)
                        self.assertEqual(live.spot, (field, MINUTES))
                        live(*[1 if d > 0 else -1] * abs(d), gap=0.09)
                        held = Hand(kind=kind, step=step, **{field: secs(start)})(*presses)
                        held(Held(d))
                        want = spec_minutes_burst(secs(start), d, step)
                        self.assertEqual((live.value(), held.value()), (want, want),
                                         (kind, field, step, start, d))

    def test_the_spec_s_examples(self):
        h = Hand(step=5)("ok")                                 # WORK 0:20, minutes
        self.assertEqual([h(-1).shown(), h(1).shown()], ["59:20", "0:20"])   # 0 <-> 59
        for start, d, want in (("1:00", -1, "0:05"), ("59:00", 1, "0:05"),
                               ("58:03", 3, "1:05")):
            for held in (False, True):
                with self.subTest(start=start, held=held):
                    h = Hand(step=5, work=secs(start))("ok")
                    if held:
                        h(Held(d))
                    else:
                        h(*[d // abs(d)] * abs(d))
                    self.assertEqual(h.shown(), want)

    def test_full_laps(self):
        for step in STEPS:
            for start in ("0:03", "0:20", "5:03", "5:30", "59:03", "59:59", "30:00"):
                v = secs(start)
                m, s = divmod(v, 60)
                for d in (60, -60, 120, -120):
                    with self.subTest(step=step, start=start, d=d):
                        self.assertEqual(app.step_minutes(v, d, step), m * 60 + max(s, step))
                for d in (61, -61):
                    with self.subTest(step=step, start=start, d=d):
                        self.assertEqual(app.step_minutes(v, d, step),
                                         (m + d) % 60 * 60 + max(s, step))

    def test_saved_odd_values(self):
        # (saved, step, delta, minutes after it)
        cases = [("0:03", 5, -1, "59:03"), ("0:03", 5, 1, "1:03"), ("0:03", 5, -2, "58:03"),
                 ("0:03", 5, 60, "0:05"), ("0:03", 5, -60, "0:05"), ("0:03", 1, 60, "0:03"),
                 ("0:03", 15, 61, "1:15"), ("0:03", 10, -61, "59:10"),
                 ("0:03", 5, 120, "0:05"), ("0:03", 1, -1, "59:03"),
                 ("0:58", 15, -1, "59:58"), ("0:58", 15, 1, "1:58"), ("0:58", 15, 60, "0:58"),
                 ("0:58", 5, -61, "59:58"),
                 ("59:59", 5, 1, "0:59"), ("59:59", 15, 2, "1:59"), ("59:59", 5, -1, "58:59"),
                 ("59:59", 1, 60, "59:59"), ("59:59", 15, -120, "59:59"),
                 ("59:03", 1, 1, "0:03"), ("59:03", 5, 1, "0:05"), ("59:03", 10, 1, "0:10"),
                 ("59:03", 15, 1, "0:15"), ("59:03", 5, 2, "1:05"), ("59:03", 5, -1, "58:03"),
                 ("59:03", 5, -59, "0:05"), ("59:03", 5, -58, "1:03"),
                 ("59:03", 15, 61, "0:15"), ("59:03", 15, -61, "58:15")]
        for saved, step, d, want in cases:
            for kind, field in ((TABATA, "work"), (TABATA, "rest"), (FIX_REST, "rest"),
                                (FIX_WORK, "work")):
                presses = ["ok"] + ["ok"] * (2 * TYPE_FIELDS[kind].index(field))
                for held in (False, True):
                    with self.subTest(saved=saved, step=step, d=d, field=field, held=held):
                        h = Hand(kind=kind, step=step, **{field: secs(saved)})(*presses)
                        self.assertEqual((h.spot, h.shown()), ((field, MINUTES), saved))
                        if held:
                            h(Held(d))
                        else:
                            h(*[d // abs(d)] * abs(d), gap=0.09)
                        self.assertEqual(h.shown(), want)

    def test_the_seconds_after_a_wrap(self):
        # (saved, step, minutes turned, the seconds' detents, times shown)
        for saved, step, d, turns, want in (
                ("0:20", 5, -1, [1, 1], ["59:25", "59:30"]),
                ("0:03", 5, -1, [-1], ["59:00"]),             # snapped on its first detent
                ("0:03", 5, -1, [1], ["59:05"]),
                ("59:03", 5, 1, [-1, -1], ["0:55", "0:50"]),  # 0:05 is the lowest: wraps
                ("59:55", 5, 1, [1, 1], ["0:05", "0:10"]),
                ("59:00", 15, 1, [-1, 1], ["0:45", "0:15"])):
            with self.subTest(saved=saved, step=step):
                h = Hand(step=step, work=secs(saved))("ok", d, "ok")
                self.assertEqual(h.spot, ("work", SECONDS))
                self.assertEqual([h(t).shown() for t in turns], want)

    def test_the_lowest_and_the_highest_time_wrap_into_each_other(self):
        for step in STEPS:
            with self.subTest(step=step):
                low, high = "0:%02d" % step, "59:%02d" % (60 - step)
                h = Hand(step=step, work=step)("ok")           # the lowest, its minutes
                h(-1, "ok", -1, -1)                            # 59:<step>, 59:00, the top
                self.assertEqual(h.shown(), high)
                h("back", 1, "ok", 1)                          # 0:<top>, then up: the lowest
                self.assertEqual(h.shown(), low)

    def test_never_an_invalid_time(self):
        for step in STEPS:
            for value in SOME_VALUES:
                for d in BURSTS + tuple(-d for d in BURSTS):
                    got = app.step_minutes(value, d, step)
                    self.assertTrue(app.TIME_MIN <= got <= app.TIME_MAX, (step, value, d))
                    cfg = app.clean_config({"types": {TABATA: {"work": got}}})
                    self.assertEqual(cfg["types"][TABATA]["work"], got)
                    if got < 60:                       # ended on 0 minutes
                        self.assertGreaterEqual(got, step, (step, value, d))

    def test_the_summary_and_the_workout_use_the_wrapped_time(self):
        h = Hand()("ok", -1, "ok", "ok", -2, "ok", "ok", "ok")   # 59:20, 58:10
        self.assertEqual(h.spot, SUMMARY)
        els = {el["id"]: el for el in app.render(h.c, h.now)}
        self.assertEqual(els["value"]["text"], "59:20/58:10 x8")
        h("start")
        self.assertEqual((h.c.workout.work, h.c.workout.rest), (secs("59:20"), secs("58:10")))

    def test_a_wrap_is_saved_on_the_next_press(self):
        h = Hand()("ok", -1)
        self.assertEqual(h.shown(), "59:20")
        self.assertFalse(h.c.save_due)
        h("ok")
        self.assertTrue(h.c.save_due)
        self.assertEqual(app.clean_config(copy.deepcopy(h.c.cfg)), h.c.cfg)


# --- STEP changed between visits; every detent, bounces, the recap -----------

class StepSwitchTest(unittest.TestCase):
    def revisit_with(self, h, step):
        """From WORK's minutes: SETTINGS, set STEP to `step`, back to WORK's
        minutes."""
        h("back").choose(SETTINGS)("ok", "ok", "ok")
        while h.c.cfg["step"] != step:
            h(1)
        h("ok", "ok", "ok")
        self.assertEqual(h.spot, ("work", MINUTES))
        return h

    def test_switching_step_between_visits(self):
        # 0:13 set with a 1 s step: (step, seconds up, seconds down, minutes up then down)
        for step, up, down, round_trip in ((5, "0:15", "0:10", "0:13"),
                                           (10, "0:20", "0:10", "0:13"),
                                           (15, "0:15", "0:15", "0:15")):
            with self.subTest(step=step):
                for way, want in ((1, up), (-1, down)):
                    h = Hand(step=1)("ok", "ok", *[-1] * 7)    # 0:20 -> 0:13
                    self.assertEqual(h.shown(), "0:13")
                    self.revisit_with(h("back"), step)
                    self.assertEqual(h.shown(), "0:13")
                    h("ok")
                    self.assertEqual(h.turns(way, 1), [want])
                h = self.revisit_with(Hand(step=1)("ok", "ok", *[-1] * 7, "back"), step)
                self.assertEqual(h.turns(1, 1) + h.turns(-1, 1), ["1:13", round_trip])

    def test_back_to_a_1_s_step(self):
        h = Hand(step=15)("ok", "ok", 1, 1)                    # 0:20 -> 0:30 -> 0:45
        self.assertEqual(h.shown(), "0:45")
        self.revisit_with(h("back"), 1)("ok")
        self.assertEqual(h.turns(1, 2), ["0:46", "0:47"])

    def test_a_long_time_snaps_on_its_first_seconds_detent(self):
        for way, want in ((1, "12:45"), (-1, "12:30")):
            h = Hand(step=1, work=secs("12:34"))("ok")
            self.revisit_with(h, 15)("ok")
            self.assertEqual(h.turns(way, 1), [want])


class WheelTest(unittest.TestCase):
    def test_every_detent_counts_held_or_live_at_any_speed(self):
        h = Hand()("ok")                                       # WORK 0:20, minutes
        h.turns(1, 25, gap=0.01)
        self.assertEqual(h.shown(), "25:20")
        h(Held(7))
        self.assertEqual(h.shown(), "32:20")
        h(Held(-92))                                           # down to 0, then a lap
        self.assertEqual(h.shown(), "0:20")
        h("ok")                                                # seconds
        h.turns(1, 13, gap=0.01)                               # a lap of 11, then 2
        self.assertEqual(h.shown(), "0:30")
        h(Held(-11))
        self.assertEqual(h.shown(), "0:30")

    def handle(self, h, delta, bar_ms, held=False):
        h.c.handle(Wheel(delta, BAR0 + bar_ms / 1000.0, held), T0 + bar_ms / 1000.0)

    def test_a_single_live_detent_back_within_80_ms_is_ignored_on_both_parts(self):
        for part in (MINUTES, SECONDS):
            with self.subTest(part=part):
                h = Hand(work=secs("5:20"))("ok", *(["ok"] if part == SECONDS else []))
                self.handle(h, 1, 0)
                after = h.value()
                self.handle(h, -1, 50)
                self.assertEqual(h.value(), after)

    def test_what_is_not_a_bounce(self):
        cases = {"held back": (Wheel(-1, None, True), 50),
                 "two back": (Wheel(-2, None, False), 50),
                 "same way": (Wheel(1, None, False), 10),
                 "back at 80 ms": (Wheel(-1, None, False), 80)}
        for name, (wheel, ms) in cases.items():
            for part in (MINUTES, SECONDS):
                with self.subTest(name=name, part=part):
                    h = Hand(work=secs("5:20"))("ok", *(["ok"] if part == SECONDS else []))
                    self.handle(h, 1, 0)
                    after = h.value()
                    self.handle(h, wheel.delta, ms, wheel.held)
                    detent = app.step_minutes if part == MINUTES else app.step_seconds
                    self.assertEqual(h.value(), detent(after, wheel.delta, 5))

    def test_a_press_between_ends_the_turn(self):
        h = Hand(work=secs("5:20"))("ok")
        self.handle(h, 1, 0)                                   # minutes: 6:20
        h.c.handle("ok", T0 + 0.02)                            # on to the seconds
        self.handle(h, -1, 40)
        self.assertEqual(h.shown(), "6:15")

    def test_recap_paging_is_unchanged(self):
        h = Hand(kind=FIX_WORK, work=2)
        h.c.cfg["get_ready"] = 0
        h.c.cfg["types"][FIX_WORK]["rounds"] = 1
        h("ok", "ok", "ok", "ok", "start").wait(3.0)
        self.assertEqual(h.spot, RECAP)
        first = h.c.recap_page(h.now)
        pages = app.RECAP_PAGES
        h(Held(3))
        self.assertIsNone(h.c.page)                            # a flick: ignored
        h(Held(2))
        self.assertEqual(h.c.page, pages[(pages.index(first) + 2) % 4])
        h(Held(-1))
        self.assertEqual(h.c.page, pages[(pages.index(first) + 1) % 4])
        h(-1)
        self.assertEqual(h.c.page, first)
        h(Held(-5))
        self.assertEqual(h.c.page, first)


# --- OK and BACK through the setup -------------------------------------------

class WalkTest(unittest.TestCase):
    def walk(self, kind, steps):
        """`steps`: [(event, spot after it)], from TYPE with `kind` selected."""
        h = Hand(kind=kind)
        self.assertEqual(h.spot, ("type", kind))
        for i, (event, want) in enumerate(steps):
            h(event)
            self.assertEqual(h.spot, want, "after step %d (%r)" % (i, event))
        return h

    def test_tabata(self):
        w, r = "work", "rest"
        self.walk(TABATA, [
            ("ok", (w, MINUTES)), ("ok", (w, SECONDS)), ("ok", (r, MINUTES)),
            ("ok", (r, SECONDS)), ("ok", "rounds"), ("ok", SUMMARY),
            ("back", "rounds"), ("back", (r, SECONDS)), ("back", (r, MINUTES)),
            ("back", (w, SECONDS)), ("back", (w, MINUTES)), ("ok", (w, SECONDS)),
            ("ok", (r, MINUTES)), ("ok", (r, SECONDS)), ("start", (r, SECONDS)),
            ("back", (r, MINUTES)), ("back", (w, SECONDS)), ("back", (w, MINUTES)),
            ("back", ("type", TABATA)), ("back", ("type", TABATA))])

    def test_fixed_rest_has_only_rest(self):
        r = "rest"
        h = self.walk(FIX_REST, [
            ("ok", (r, MINUTES)), ("ok", (r, SECONDS)), ("ok", "rounds"), ("ok", SUMMARY),
            ("back", "rounds"), ("back", (r, SECONDS)), ("back", (r, MINUTES)),
            ("ok", (r, SECONDS)), ("back", (r, MINUTES)), ("back", ("type", FIX_REST))])
        self.assertEqual(h.c.cfg["types"][FIX_REST], app.default_config()["types"][FIX_REST])

    def test_fixed_work_has_only_work(self):
        w = "work"
        self.walk(FIX_WORK, [
            ("ok", (w, MINUTES)), ("ok", (w, SECONDS)), ("ok", "rounds"), ("ok", SUMMARY),
            ("back", "rounds"), ("back", (w, SECONDS)), ("ok", "rounds"),
            ("back", (w, SECONDS)), ("back", (w, MINUTES)), ("back", ("type", FIX_WORK))])

    def test_ok_and_back_never_change_a_time(self):
        for kind in app.TYPES:
            with self.subTest(kind=kind):
                h = Hand(kind=kind, work=secs("0:58"), rest=secs("0:03"))
                h("ok", "ok", "back", "ok", "ok", "back", "back", "ok", "ok", "ok")
                if kind == TABATA:
                    h("ok", "back", "ok", "ok")
                self.assertIn(h.c.screen, (app.MENU, SUMMARY))
                self.assertEqual((h.value("work"), h.value("rest")), (58, 3))

    def test_turns_change_only_the_part_on_screen_of_that_type(self):
        for kind, field in ((TABATA, "work"), (TABATA, "rest"), (FIX_REST, "rest"),
                            (FIX_WORK, "work")):
            with self.subTest(kind=kind, field=field):
                h = Hand(kind=kind)("ok")
                while h.c.field != field:
                    h("ok")
                before = app.default_config()["types"]
                h(2)                                           # minutes: +2
                h("ok", -1)                                    # seconds: one step down
                types = h.c.cfg["types"]
                want = dict(before[kind])
                want[field] = before[kind][field] + 120 - 5
                self.assertEqual(types[kind], want)
                for other in app.TYPES:
                    if other != kind:
                        self.assertEqual(types[other], before[other])

    def test_a_time_opens_on_its_minutes_after_a_workout_and_after_settings(self):
        h = Hand(kind=FIX_WORK, work=2)
        h.c.cfg["get_ready"] = 0
        h.c.cfg["types"][FIX_WORK]["rounds"] = 1
        h("ok", "ok", "ok", "ok", "start")
        self.assertEqual(h.spot, RUN)
        h.wait(3.0)                                    # the 2 s WORK runs out
        self.assertEqual(h.spot, RECAP)
        h("back", "ok")
        self.assertEqual(h.spot, ("work", MINUTES))
        h("ok", "back", "back").choose(SETTINGS)("ok", "back").choose(FIX_WORK)("ok")
        self.assertEqual(h.spot, ("work", MINUTES))

    def test_a_saved_time_below_the_step_runs_as_saved(self):
        for kind, field, seconds in ((FIX_WORK, "work", 3), (FIX_REST, "rest", 3),
                                     (TABATA, "work", 3599)):
            with self.subTest(kind=kind):
                h = Hand(kind=kind, step=15, **{field: seconds})
                h("ok", *["ok"] * (1 + 2 * len([f for f in TYPE_FIELDS[kind]
                                                if f in TIME_FIELDS])))
                self.assertEqual(h.spot, SUMMARY)
                h("start")
                self.assertEqual(getattr(h.c.workout, field), seconds)

    def test_turns_are_saved_on_the_next_press_including_a_part_change(self):
        h = Hand()("ok", 1)
        self.assertFalse(h.c.save_due)
        h("ok")                                        # minutes -> seconds
        self.assertTrue(h.c.save_due)
        h.c.saved()
        h(1)
        self.assertFalse(h.c.save_due)
        h("back")                                      # seconds -> minutes
        self.assertTrue(h.c.save_due)
        self.assertEqual(h.shown(), "1:25")


class BackWalkTest(unittest.TestCase):
    def assert_walk(self, h, events, want):
        for i, (event, where) in enumerate(zip(events, want)):
            h(event)
            self.assertEqual(h.spot, where, "after event %d (%r)" % (i, event))

    def test_tabata_from_the_summary_to_type(self):
        h = Hand()(*to_summary(TABATA))
        self.assertEqual(h.spot, SUMMARY)
        self.assert_walk(h, ["back"] * 8, [
            "rounds", ("rest", SECONDS), ("rest", MINUTES), ("work", SECONDS),
            ("work", MINUTES), ("type", TABATA), ("type", TABATA), ("type", TABATA)])

    def test_the_fixed_types_with_their_one_time(self):
        for kind, f in ((FIX_REST, "rest"), (FIX_WORK, "work")):
            with self.subTest(kind=kind):
                h = Hand(kind=kind)(*to_summary(kind))
                self.assertEqual(h.spot, SUMMARY)
                self.assert_walk(h, ["back"] * 5, [
                    "rounds", (f, SECONDS), (f, MINUTES), ("type", kind), ("type", kind)])

    def test_ok_after_every_stop_of_the_walk_goes_one_part_on(self):
        for kind in TYPES:
            line = line_of(kind)
            for k in range(1, len(line)):
                with self.subTest(kind=kind, backs=k):
                    h = Hand(kind=kind)(*to_summary(kind))
                    h(*["back"] * k)
                    self.assertEqual(h.spot, line[-1 - k])
                    h("ok")
                    self.assertEqual(h.spot, line[-k])        # forward: a time on its minutes

    def test_every_short_ok_back_start_sequence_follows_the_line(self):
        # Odd saved times, so a press that changed a value would show.
        for kind in TYPES:
            line = line_of(kind)
            for seq in itertools.product(("ok", "back", "start"), repeat=6):
                h = Hand(kind=kind, work=3, rest=3599)
                i = 0
                for n, button in enumerate(seq):
                    if line[i] == SUMMARY and button == "start":
                        break                                  # the workout: not this test
                    i = {"ok": min(i + 1, len(line) - 1), "back": max(i - 1, 0),
                         "start": i}[button]
                    h(button, gap=0.37)
                    if h.spot != line[i]:
                        self.fail("%s %s: at %r after %d presses, SPEC %r"
                                  % (kind, seq, h.spot, n + 1, line[i]))
                    if isinstance(line[i], tuple) and line[i][0] in TIME_FIELDS \
                            and button != "start":
                        for dt, want in ((0.2, None), (0.7, line[i][1]), (1.2, None)):
                            got = hidden(h.c, h.now + dt)
                            if got != want:
                                self.fail("%s %s, press %d: %r hidden %.1f s after, SPEC %r"
                                          % (kind, seq, n + 1, got, dt, want))
                self.assertEqual((h.c.cfg["types"][kind]["work"],
                                  h.c.cfg["types"][kind]["rest"]), (3, 3599))

    def test_back_into_a_time_turns_its_seconds_and_back_again_its_minutes(self):
        h = Hand()(*to_summary(TABATA))                        # 0:20 / 0:10
        h("back", "back")
        self.assertEqual(h.spot, ("rest", SECONDS))
        h(1)
        self.assertEqual(h.shown("rest"), "0:15")
        h("back", -1)                                          # REST's minutes, down past 0
        self.assertEqual((h.spot, h.shown("rest")), (("rest", MINUTES), "59:15"))
        h("back", 1)                                           # WORK's seconds
        self.assertEqual((h.spot, h.shown("work")), (("work", SECONDS), "0:25"))
        h("back", -2)                                          # WORK's minutes
        self.assertEqual((h.spot, h.shown("work")), (("work", MINUTES), "58:25"))
        h("back")
        self.assertEqual(h.spot, ("type", TABATA))
        self.assertEqual(app.summary_text(TABATA, h.c.cfg["types"][TABATA]),
                         "58:25/59:15 x")

    def finish(self, h, kind, how):
        """START on the summary, reach the recap `how`, BACK to TYPE."""
        h("start")
        self.assertEqual(h.spot, RUN)
        if how == "ran":
            h.wait(2.5)                                        # a 2 s WORK, 1 round
        elif how == "skipped":
            h("ok", gap=1.0)                                   # the open WORK, skipped
        elif how == "stopped":
            h("back", "back", gap=0.2)
        elif how == "pending":
            h("back", gap=1.5)                                 # STOP? up
            h.wait(1.0)                                        # the 2 s WORK runs out
            self.assertEqual(h.spot, RECAP)
            h("back", gap=0.2)                                 # meant for STOP?: ignored
        self.assertEqual(h.spot, RECAP)
        self.assertEqual(h.c.workout.stopped, how == "stopped")
        h("back", gap=0.2)
        self.assertEqual(h.spot, ("type", kind))

    def test_after_a_recap_the_walk_is_the_same(self):
        for kind, how in ((TABATA, "ran"), (FIX_REST, "skipped"), (FIX_WORK, "stopped"),
                          (TABATA, "pending"), (FIX_WORK, "ran")):
            with self.subTest(kind=kind, how=how):
                line = line_of(kind)
                h = Hand(kind=kind, get_ready=0, work=2, rest=1, rounds=1)
                h(*to_summary(kind), "back", "back", "ok", "ok")    # a walk before it
                self.assertEqual(h.spot, SUMMARY)
                self.finish(h, kind, how)
                self.assert_walk(h, ["ok"] * (len(line) - 1), line[1:])
                self.assert_walk(h, ["back"] * len(line), line[-2::-1] + [line[0]])

    def test_after_settings_the_walk_is_the_same(self):
        for field_i in range(len(SETTINGS_FIELDS)):
            with self.subTest(field=SETTINGS_FIELDS[field_i]):
                h = Hand().choose(SETTINGS)("ok", *["ok"] * field_i)
                self.assertEqual(h.spot, SETTINGS_FIELDS[field_i])
                h("back")                                      # any SETTINGS field -> TYPE
                self.assertEqual(h.spot, ("type", SETTINGS))
                h("back")
                self.assertEqual(h.spot, ("type", SETTINGS))   # nothing on TYPE
                h.choose(TABATA)
                line = line_of(TABATA)
                self.assert_walk(h, ["ok"] * (len(line) - 1), line[1:])
                self.assert_walk(h, ["back"] * (len(line) - 1), line[-2::-1])
        h = Hand(kind=FIX_REST).choose(SETTINGS)(*["ok"] * (1 + len(SETTINGS_FIELDS)))
        self.assertEqual(h.spot, ("type", FIX_REST))           # OK on SKIP WITH
        line = line_of(FIX_REST)
        self.assert_walk(h, ["ok"] * (len(line) - 1) + ["back"] * (len(line) - 1),
                         line[1:] + line[-2::-1])

    def test_after_picking_another_type_the_walk_is_that_type_s(self):
        h = Hand()(*to_summary(TABATA), *["back"] * 6)
        self.assertEqual(h.spot, ("type", TABATA))
        h.choose(FIX_WORK)
        line = line_of(FIX_WORK)
        self.assert_walk(h, ["ok"] * (len(line) - 1) + ["back"] * (len(line) - 1),
                         line[1:] + line[-2::-1])

    def test_turns_between_backs_dont_change_the_walk(self):
        h = Hand()(*to_summary(TABATA))
        line = line_of(TABATA)
        for k in range(1, len(line)):
            h("back")
            self.assertEqual(h.spot, line[-1 - k])
            if k < len(line) - 1:                              # not the TYPE wheel
                h(2, -1)
                self.assertEqual(h.spot, line[-1 - k])

    def test_the_menu_ignores_start_on_a_time(self):
        for part in (MINUTES, SECONDS):
            h = Hand(work=secs("0:03"))("ok", *(["ok"] if part == SECONDS else []))
            h("start", ("release", "start"))
            self.assertEqual((h.spot, h.shown("work")), (("work", part), "0:03"))


# --- the blink ---------------------------------------------------------------

def lit(c, now):
    els = {el["id"]: el for el in app.render(c, now)}
    return {s for s in app.CLOCK_SLOTS if not app.is_blank(els[s])}


class BlinkTest(BlinkChecks, unittest.TestCase):
    """The part being set blinks 0.5 s on, 0.5 s off from the press that
    reached it; after a detent it stays lit for 1 s first (SPEC 6)."""

    def on_work(self, part, at=T0, **times):
        """TABATA's WORK, its `part` being set since a press at `at`."""
        c = app.Controller(app.default_config())
        c.cfg["types"][TABATA].update(times)
        if part == SECONDS:
            c.handle("ok", at - 0.1)
        c.handle("ok", at)
        self.assertEqual((c.field, c.part), ("work", part))
        return c

    def test_the_rhythm_after_a_press_without_drift(self):
        L = LIT_AFTER_PRESS
        moments = [0, 0.25, L - 0.01, L, L + 0.25, L + 0.49, L + 0.5, L + 0.99, L + 1.0,
                   L + 1.5, 3600.2, 3600.7, 86400.1, 86400.6]
        for part in (MINUTES, SECONDS):
            c = self.on_work(part)
            parts = clock_parts("0:20")
            whole = parts[MINUTES] | parts[SECONDS] | parts["colon"]
            for t in moments:
                with self.subTest(part=part, t=t):
                    want = whole - parts[part] if spec_hidden(part, t, False) else whole
                    self.assertEqual(lit(c, T0 + t), want)

        def off(t):
            return spec_hidden(MINUTES, t, False) == MINUTES
        self.assertFalse(off(L - 0.01))                        # the model itself
        self.assertTrue(off(L) and off(L + 0.49))
        self.assertFalse(off(L + 0.5) or off(L + 0.99))

    def test_the_colon_and_the_other_part_never_blink(self):
        for txt in ("0:05", "9:59", "10:00", "59:59"):
            for part in (MINUTES, SECONDS):
                c = self.on_work(part, work=secs(txt))
                parts = clock_parts(txt)
                steady = parts["colon"] | parts[SECONDS if part == MINUTES else MINUTES]
                for i in range(0, 60):
                    with self.subTest(txt=txt, part=part, t=i / 20):
                        self.assertLessEqual(steady, lit(c, T0 + i / 20))

    def test_presses_on_other_screens_start_it_lit(self):
        h = Hand()("ok", "ok", "ok", "ok", "ok", "ok")         # the summary
        self.assertEqual(h.spot, SUMMARY)
        h.wait(5.0)
        h("back", gap=5.0)                                     # ROUNDS: nothing blinks
        self.assertEqual(h.spot, "rounds")
        self.assertEqual(lit(h.c, h.now + OFF), lit(h.c, h.now + 0.2))
        h("back", gap=5.0)                                     # REST's seconds
        self.assertEqual(h.spot, ("rest", SECONDS))
        self.assertEqual(lit(h.c, h.now + LIT_AFTER_PRESS - 0.05), {"c0", "c1", "c2", "c3"})
        self.assertEqual(lit(h.c, h.now + LIT_AFTER_PRESS + 0.05), {"c2", "c3"})

    def test_button_releases_dont_restart_it(self):
        h = Hand()("ok")
        h("ok", gap=2.0)                                       # the seconds, at h.now
        t = h.now
        for button in ("ok", "back", "start"):
            with self.subTest(button):
                # Released 0.1 s before a moment the press says is off: had
                # the release restarted the blink, it would be lit.
                h.c.handle(("release", button), t + OFF - 0.1)
                self.assertEqual(lit(h.c, t + OFF), {"c2", "c3"})

    def test_every_kind_of_detent_keeps_it_lit(self):
        # A held burst, a detent wrapping 59 minutes to 0, and a contact bounce
        # (ignored as a turn, but the wheel is being turned, so the bounce
        # restarts it too). SPEC 6: "After a wheel detent it stays lit for 1 s".
        for name, events in (("held", [Wheel(3, BAR0, True)]),
                             ("wrapped", [Wheel(1, BAR0, False)]),
                             ("bounce", [Wheel(1, BAR0, False), Wheel(-1, BAR0 + 0.03, False)])):
            with self.subTest(name):
                c = self.on_work(MINUTES, work=secs("59:20") if name == "wrapped" else 20)
                before = c.cfg["types"][TABATA]["work"]
                t = T0 + OFF                                   # the minutes are off
                self.assertNotIn("c3", lit(c, t))
                for i, ev in enumerate(events):
                    c.handle(ev, t + 0.03 * i)
                last = t + 0.03 * (len(events) - 1)
                txt = mmss(c.cfg["types"][TABATA]["work"])
                whole = set().union(*clock_parts(txt).values())
                self.assertEqual(lit(c, last + LIT_AFTER_DETENT - 0.01), whole)
                self.assertEqual(lit(c, last + LIT_AFTER_DETENT + 0.01),
                                 whole - clock_parts(txt)[MINUTES])
                if name == "wrapped":
                    self.assertEqual(c.cfg["types"][TABATA]["work"], secs("0:20"))
                if name == "bounce":
                    self.assertEqual(c.cfg["types"][TABATA]["work"], before + 60)

    def test_ok_and_back_move_the_blink_to_the_other_part(self):
        c = self.on_work(MINUTES, work=secs("12:34"))
        whole = {"c0", "c1", "c2", "c3", "c4"}
        t = T0 + OFF
        self.assertEqual(lit(c, t), {"c0", "c1", "c2"})
        c.handle("ok", t)                                      # on to the seconds
        self.assertEqual(lit(c, t), whole)
        self.assertEqual(lit(c, t + OFF), {"c2", "c3", "c4"})
        c.handle("back", t + OFF)                              # back to the minutes
        self.assertEqual(lit(c, t + OFF), whole)
        self.assertEqual(lit(c, t + 2 * OFF), {"c0", "c1", "c2"})

    def test_reached_by_ok_and_by_back_in_every_type(self):
        for kind in TYPES:
            line = line_of(kind)
            for gap in (0.3, 0.77, 1.3):
                h = Hand(kind=kind, work=secs("12:34"), rest=secs("0:05"))
                for button, where in [("ok", w) for w in line[1:]] + \
                        [("back", w) for w in line[-2::-1]]:
                    h(button, gap=gap)
                    self.assertEqual(h.spot, where)
                    if isinstance(where, tuple) and where[0] in TIME_FIELDS:
                        self.assert_rhythm(h, h.now, False, msg="%s %s %s" % (kind, button,
                                                                             where))

    def test_back_to_rounds_then_into_rest_s_seconds_counts_from_the_second_back(self):
        # If the blink counted from the first BACK (or the summary's OK),
        # some of these would be off when they should be lit.
        for delay in (0.1, 0.3, 0.45, 0.6, 0.77, 1.2, 2.5, 30.0):
            with self.subTest(delay=delay):
                h = Hand()(*to_summary(TABATA))
                h("back")
                self.assertEqual(h.spot, "rounds")
                self.assertEqual(app.render(h.c, h.now + 0.7), app.render(h.c, h.now + 0.2))
                h("back", gap=delay)
                self.assertEqual(h.spot, ("rest", SECONDS))
                self.assert_rhythm(h, h.now, False)
                h("back", gap=0.7)                             # on to the minutes
                self.assertEqual(h.spot, ("rest", MINUTES))
                self.assert_rhythm(h, h.now, False)

    def test_turned_rounds_then_back_into_rest_is_the_press_rhythm(self):
        h = Hand()(*to_summary(TABATA), "back", 1, 1)          # ROUNDS turned
        h("back", gap=0.2)
        self.assertEqual(h.spot, ("rest", SECONDS))
        self.assert_rhythm(h, h.now, False)

    def test_a_detent_then_a_press_is_the_press_rhythm(self):
        for first, press, where in (((MINUTES,), "ok", ("work", SECONDS)),
                                    ((MINUTES, SECONDS), "back", ("work", MINUTES)),
                                    ((MINUTES, SECONDS), "ok", ("rest", MINUTES))):
            with self.subTest(press=press, where=where):
                h = Hand()("ok", *["ok"] * (len(first) - 1))
                h(1, Held(2))
                h(press, gap=0.2)
                self.assertEqual(h.spot, where)
                self.assert_rhythm(h, h.now, False)

    def test_a_press_then_a_detent_lights_it_at_once_for_1_s(self):
        for part in (MINUTES, SECONDS):
            for event in (1, -1, Held(3), Held(-61), Held(60)):
                with self.subTest(part=part, event=event):
                    h = Hand(work=secs("0:03"))("ok", *(["ok"] if part == SECONDS else []))
                    h.wait(0.7)
                    self.assertEqual(hidden(h.c, h.now), part)  # off when the wheel turns
                    h(event, gap=0.0)
                    self.assert_rhythm(h, h.now, True)

    def test_a_bounce_is_ignored_and_the_part_stays_lit_for_a_second(self):
        # The bounce comes 50 ms after the detent. Lit for 1 s from either
        # of them is fine: only times on which both agree are checked.
        agreed = ((0.0, False), (0.5, False), (0.99, False), (1.1, True), (1.45, True),
                  (1.6, False), (1.95, False), (2.1, True), (2.45, True))
        for part, start, way, want in ((MINUTES, "0:03", 1, "1:03"),
                                       (MINUTES, "59:20", 1, "0:20"),
                                       (MINUTES, "1:03", -1, "0:05"),
                                       (MINUTES, "0:20", -1, "59:20"),
                                       (SECONDS, "0:05", -1, "0:55"),
                                       (SECONDS, "1:55", 1, "1:00")):
            with self.subTest(part=part, start=start, way=way):
                h = Hand(work=secs(start))("ok", *(["ok"] if part == SECONDS else []))
                h(way)
                at = h.now
                h(-way, gap=0.05)                              # the contact bounces back
                self.assertEqual(h.shown("work"), want)
                for dt, off in agreed:
                    self.assertEqual(hidden(h.c, at + dt), part if off else None, dt)

    def test_releases_dont_restart_it(self):
        # (events, the event that set the rhythm, a detent?, release, after it)
        cases = (("back into REST's seconds", to_summary(TABATA) + ["back", "back"], False,
                  ("release", "back"), 0.3),
                 ("ok into WORK's minutes", ["ok"], False, ("release", "ok"), 0.45),
                 ("back to WORK's minutes", ["ok", "ok", "back"], False,
                  ("release", "back"), 0.49),
                 ("a detent", ["ok", 1], True, ("release", "ok"), 0.1),
                 ("a detent, then START let go", ["ok", 1], True, ("release", "start"), 0.6))
        for name, events, detent, release, after in cases:
            with self.subTest(name):
                h = Hand()(*events)
                at = h.now
                h(release, gap=after)
                self.assert_rhythm(h, at, detent)

    def test_a_wrapped_two_digit_minute_blinks_whole(self):
        h = Hand()("ok", -1)                                   # 0:20 -> 59:20
        self.assertEqual(h.shown(), "59:20")
        self.assert_rhythm(h, h.now, True)                     # c3 and c4, never one
        h(1)                                                   # 59:20 -> 0:20
        self.assertEqual(h.shown(), "0:20")
        self.assert_rhythm(h, h.now, True)


# --- START in the menu; DETENT_LIT -------------------------------------------

def menu_spots():
    """(kind, presses from TYPE, spot) for every part of every time, reached
    by OK and, from the summary, by BACK."""
    for kind in TYPES:
        line = line_of(kind)
        for k, where in enumerate(line):
            if isinstance(where, tuple) and where[0] in TIME_FIELDS:
                yield kind, ["ok"] * k, where
                yield kind, to_summary(kind) + ["back"] * (len(line) - 1 - k), where


class StartInTheMenuTest(BlinkChecks, unittest.TestCase):
    """SPEC 3: START does nothing in the menu. SPEC 6: the blink counts from
    the press that reached the part, or from the last detent. SPEC 4: a
    change is saved on the next button press, START included."""

    def test_start_keeps_the_press_rhythm_everywhere(self):
        for kind, presses, where in menu_spots():
            for skip_with in app.SKIP_BUTTONS:                 # the menu keeps its buttons
                for after in (0.1, 0.3, 0.6, 0.77, 1.2, 1.7):
                    with self.subTest(kind=kind, where=where, presses=len(presses),
                                      skip_with=skip_with, after=after):
                        h = Hand(kind=kind, skip_with=skip_with, work=secs("12:34"),
                                 rest=secs("0:05"))(*presses)
                        self.assertEqual(h.spot, where)
                        at = h.now
                        h("start", gap=after)
                        h(("release", "start"), gap=0.05)
                        self.assertEqual(h.spot, where)
                        self.assert_rhythm(h, at, False, msg="START %.2f s after" % after)

    def test_start_doesnt_cut_short_the_second_after_a_detent(self):
        for part in (MINUTES, SECONDS):
            for event in (1, -1, Held(3), Held(-2)):
                for after in (0.05, 0.3, 0.6, 0.9, 0.99):
                    with self.subTest(part=part, event=event, after=after):
                        h = Hand(work=secs("5:30"))("ok", *(["ok"] if part == SECONDS else []))
                        h(event)
                        at = h.now
                        h("start", gap=after)
                        self.assert_rhythm(h, at, True)

    def test_start_while_off_leaves_it_off(self):
        # START must not light a part that is blinking off.
        h = Hand()("ok")
        at = h.now
        h.wait(0.6)
        self.assertEqual(hidden(h.c, h.now), MINUTES)
        h("start", gap=0.0)
        self.assertEqual(hidden(h.c, h.now), MINUTES)
        self.assertEqual(hidden(h.c, at + 0.99), MINUTES)
        self.assertIsNone(hidden(h.c, at + 1.01))

    def test_start_is_still_the_press_that_saves_a_change(self):
        cases = [(["ok"], 1), (["ok", "ok"], -1), (["ok", "ok", "ok"], 2), (["ok"] * 5, -1)]
        for presses, turn in cases:
            with self.subTest(presses=len(presses)):
                h = Hand()(*presses)
                where = h.spot
                h(turn)
                value = copy.deepcopy(h.c.cfg)
                self.assertFalse(h.c.save_due)
                h(("release", "start"))
                self.assertFalse(h.c.save_due)                 # a release is no press
                h("start")
                self.assertTrue(h.c.save_due)
                self.assertEqual((h.spot, h.c.cfg), (where, value))   # and nothing else
                h.c.saved()
                h("start")
                self.assertFalse(h.c.save_due)                 # nothing new to save
        for i, field in enumerate(SETTINGS_FIELDS):
            with self.subTest(field=field):
                h = Hand().choose(SETTINGS)("ok", *["ok"] * i)
                h(1)
                self.assertFalse(h.c.save_due)
                h("start")
                self.assertTrue(h.c.save_due)
                self.assertEqual(h.spot, field)

    def test_start_ends_a_turn_for_the_bounce_rule(self):
        # +1, then -1 50 ms later on the bar's clock: a bounce, unless a
        # press came between them. A release is no press (SPEC 3).
        for between, want in ((None, "1:20"), ("start", "0:20"),
                              (("release", "start"), "1:20"), (("release", "ok"), "1:20")):
            with self.subTest(between=between):
                h = Hand()("ok")                               # WORK 0:20, its minutes
                h(1)
                bar = h.bar
                if between is not None:
                    h.c.handle(between, h.now + 0.02)
                h.c.handle(Wheel(-1, bar + 0.05, False), h.now + 0.05)
                self.assertEqual(h.shown("work"), want)

    def test_start_on_type_and_on_settings_does_nothing(self):
        h = Hand()
        h(1, "start", ("release", "start"))
        self.assertEqual(h.spot, ("type", FIX_REST))
        h.choose(SETTINGS)("start")
        self.assertEqual(h.spot, ("type", SETTINGS))
        for i, field in enumerate(SETTINGS_FIELDS):
            h = Hand().choose(SETTINGS)("ok", *["ok"] * i)
            cfg = copy.deepcopy(h.c.cfg)
            h("start", "start")
            self.assertEqual((h.spot, h.c.cfg), (field, cfg))
            self.assertEqual(h.c.sounds, [])


class DetentLitTest(unittest.TestCase):
    def test_the_numbers_are_spec_6_s(self):
        self.assertEqual((app.BLINK, app.DETENT_LIT), (0.5, 1.0))

    def test_the_blink_written_out(self):
        def written_out(c, now, turned):
            since = now - c.input_at - (app.BLINK if turned else 0.0)
            return c.part if app.blinked_off(max(0.0, since)) else None
        for presses in (["ok"], ["ok", "ok"], ["ok", "ok", "ok"]):    # 12:34, 12:34, 0:05
            h = Hand(work=secs("12:34"), rest=secs("0:05"))(*presses)
            for after in (False, True):
                for input_at in (0.0, T0 + 0.37, 1e6 + 0.123):
                    h.c.input_at, h.c.after_detent = input_at, after
                    for i in range(-20, 200):
                        now = input_at + i * 0.0125
                        self.assertEqual(hidden(h.c, now), written_out(h.c, now, after),
                                         (h.spot, after, input_at, i))

    def test_detent_lit_sets_the_second(self):
        for lit_for in (0.75, 1.0, 1.5):
            with self.subTest(lit_for=lit_for), mock.patch.object(app, "DETENT_LIT", lit_for):
                h = Hand()("ok")
                at = h.now
                self.assertEqual([hidden(h.c, at + dt) for dt in (0.45, 0.55)], [None, MINUTES])
                h(1, gap=0.0)
                self.assertIsNone(hidden(h.c, at + lit_for - 0.01))
                self.assertEqual(hidden(h.c, at + lit_for + 0.01), MINUTES)
                self.assertIsNone(hidden(h.c, at + lit_for + 0.51))

    def test_the_flag_follows_the_last_input(self):
        h = Hand()("ok")
        self.assertFalse(h.c.after_detent)
        h(1)
        self.assertTrue(h.c.after_detent)
        h(("release", "ok"))
        self.assertTrue(h.c.after_detent)                      # releases change nothing
        h("start")
        self.assertTrue(h.c.after_detent)                      # nor START in the menu
        h("ok")
        self.assertFalse(h.c.after_detent)


# --- BACK in SETTINGS --------------------------------------------------------

# On any SETTINGS field (GET READY, SOUND, STEP, SKIP WITH) BACK returns to
# TYPE with SETTINGS selected. OK still walks the fields, and OK on SKIP WITH
# still returns to TYPE with the last-used type. A value turned before BACK is
# kept and saved on that BACK. The workout setup (WORK/REST/ROUNDS), the
# summary, the workout and its STOP? prompt keep their BACK.

RELEASE = ("release", "back")


def setup_oks(kind):
    """OK presses from TYPE's first field to the summary."""
    return to_summary(kind)[1:]


def settings_of(cfg):
    return {k: cfg[k] for k in SETTINGS_FIELDS}


def shown_texts(c, now):
    return [el["text"] for el in app.render(c, now) if el["type"] == "text"]


ON_TYPE_SETTINGS = (MENU, "type", SETTINGS)


# (field, detents, value after the turn), starting from the defaults
# (get-ready 5 s, sound on, step 5 s, skip with OK).
TURNS = [
    ("get_ready", 1, 6), ("get_ready", -1, 4), ("get_ready", 3, 8),
    ("get_ready", -9, 0), ("get_ready", 20, 15),
    ("sound", 1, False), ("sound", -1, False), ("sound", 2, True), ("sound", 3, False),
    ("step", 1, 10), ("step", -1, 1), ("step", 3, 1), ("step", 4, 5),
    ("skip_with", 1, "start"), ("skip_with", -1, "start"), ("skip_with", 2, "ok"),
]


class BackInSettingsTest(unittest.TestCase):
    def test_back_on_every_field_goes_to_type_with_settings_selected(self):
        for kind in TYPES:
            for field in SETTINGS_FIELDS:
                with self.subTest(kind=kind, field=field):
                    h = Hand(kind=kind).to_field(field)
                    before = copy.deepcopy(h.c.cfg)
                    h.save()
                    h("back")
                    self.assertEqual(h.at, ON_TYPE_SETTINGS)
                    self.assertEqual(h.c.kind, kind)            # last-used type untouched
                    self.assertEqual(h.c.cfg, before)
                    self.assertFalse(h.c.save_due)              # nothing to save
                    self.assertIn("SETTINGS", shown_texts(h.c, h.now))
                    self.assertIn("TYPE", shown_texts(h.c, h.now))

    def test_a_turned_value_is_kept_by_back_and_saved_on_it(self):
        for field, detents, value in TURNS:
            for kind in TYPES:
                with self.subTest(field=field, detents=detents, kind=kind):
                    h = Hand(kind=kind).to_field(field)
                    h.save()
                    default = h.c.cfg[field]
                    h(detents)
                    self.assertEqual(h.c.cfg[field], value)
                    self.assertFalse(h.c.save_due)      # a turn alone never saves
                    h("back")
                    self.assertEqual(h.at, ON_TYPE_SETTINGS)
                    self.assertEqual(h.c.cfg[field], value)
                    self.assertEqual(h.c.save_due, value != default)
                    h.save()
                    if value != default:
                        self.assertEqual(h.saves[-1][field], value)
                        self.assertEqual(h.saves[-1]["last_type"], kind)
                    self.assertFalse(h.c.unsaved())

    def test_a_turn_there_and_back_then_back_saves_nothing(self):
        for field in SETTINGS_FIELDS:
            with self.subTest(field=field):
                h = Hand().to_field(field)
                h.save()
                h(1, -1, "back")
                self.assertEqual(h.at, ON_TYPE_SETTINGS)
                self.assertFalse(h.c.save_due)
                self.assertEqual(settings_of(h.c.cfg), settings_of(app.default_config()))

    def test_values_set_on_earlier_fields_survive_back(self):
        h = Hand().to_settings()
        h(-2, "ok")                         # GET READY 3 s
        h.save()
        h(1, "ok")                          # SOUND off
        h.save()
        h(1)                                # STEP 10 s, then straight out
        h("back")
        self.assertEqual(h.at, ON_TYPE_SETTINGS)
        self.assertEqual(settings_of(h.c.cfg),
                         {"get_ready": 3, "sound": False, "step": 10, "skip_with": "ok"})
        self.assertTrue(h.c.save_due)
        h.save()
        self.assertEqual(h.saves[-1]["step"], 10)

    def test_back_then_ok_reenters_settings_at_get_ready(self):
        for field in SETTINGS_FIELDS:
            with self.subTest(field=field):
                h = Hand(kind=FIX_REST).to_field(field)
                h("back", "ok")
                self.assertEqual(h.at, (MENU, "get_ready", SETTINGS))
                self.assertEqual(h.c.kind, FIX_REST)

    def test_after_back_the_wheel_moves_the_type_choice_not_a_setting(self):
        # SETTINGS is last on the TYPE wheel: +1 wraps to TABATA, -1 is FIXED WORK.
        for field in SETTINGS_FIELDS:
            for detents, choice in ((1, TABATA), (-1, FIX_WORK), (2, FIX_REST), (4, SETTINGS)):
                with self.subTest(field=field, detents=detents):
                    h = Hand(kind=FIX_REST).to_field(field)
                    before = copy.deepcopy(h.c.cfg)
                    h("back", detents)
                    self.assertEqual(h.at, (MENU, "type", choice))
                    self.assertEqual(h.c.cfg, before)           # no setting moved
                    self.assertEqual(h.c.kind, FIX_REST)        # only OK picks a type
                    if choice != SETTINGS:
                        h("ok")
                        self.assertEqual((h.at, h.c.kind),
                                         ((MENU, TYPE_FIELDS[choice][0], choice), choice))

    def test_a_turn_right_after_back_is_not_taken_for_a_bounce(self):
        # The last detent before BACK went the other way; a button clears
        # it, so a quick turn back after BACK still moves TYPE.
        for gap in (0.0, 0.01, 0.05):
            with self.subTest(gap=gap):
                h = Hand().to_field("step")
                h(1)
                h("back", gap=0.01)
                h(-1, gap=gap)
                self.assertEqual(h.at, (MENU, "type", FIX_WORK))
                self.assertEqual(h.c.cfg["step"], 10)

    def test_a_held_burst_after_back_moves_the_type_choice(self):
        h = Hand().to_field("get_ready")
        h("back")
        h.now += 0.2
        h.c.handle(Wheel(3, h.now, True), h.now)
        self.assertEqual(h.at, (MENU, "type", FIX_WORK))      # SETTINGS + 3, wrapped
        self.assertEqual(h.c.cfg["get_ready"], 5)

    def test_a_turn_and_back_in_one_message_follow_their_order(self):
        h = Hand().to_field("get_ready")
        t = h.now + 1
        h.c.handle(Wheel(2, t, True), t)                    # turn, then BACK
        h.c.handle("back", t)
        self.assertEqual((h.at, h.c.cfg["get_ready"], h.c.save_due),
                         (ON_TYPE_SETTINGS, 7, True))
        h = Hand().to_field("get_ready")
        t = h.now + 1
        h.c.handle("back", t)                               # BACK, then turn
        h.c.handle(Wheel(2, t, True), t)
        self.assertEqual((h.at, h.c.cfg["get_ready"], h.c.save_due),
                         ((MENU, "type", FIX_REST), 5, False))

    def test_the_release_after_back_does_nothing_more(self):
        for field in SETTINGS_FIELDS:
            for later in (0.0, 0.05, 0.2, 2.0):         # 2 s: a long press
                with self.subTest(field=field, later=later):
                    h = Hand().to_field(field)
                    h(1, "back")
                    h.save()
                    state = (h.at, copy.deepcopy(h.c.cfg))
                    h(RELEASE, gap=later)
                    self.assertEqual((h.at, h.c.cfg), state)
                    self.assertFalse(h.c.save_due)
                    h("ok")                                 # still where BACK left it
                    self.assertEqual(h.at, (MENU, "get_ready", SETTINGS))

    def test_a_burst_of_backs_stays_on_type_with_settings(self):
        for field in SETTINGS_FIELDS:
            for count in (2, 3, 6):
                for gap in (0.0, 0.05):
                    for releases in (False, True):
                        with self.subTest(field=field, count=count, gap=gap,
                                          releases=releases):
                            h = Hand(kind=FIX_WORK).to_field(field)
                            h(1)
                            turned = copy.deepcopy(h.c.cfg)
                            burst = (["back", RELEASE] if releases else ["back"]) * count
                            h(*burst, gap=gap)
                            self.assertEqual(h.at, ON_TYPE_SETTINGS)
                            self.assertEqual(h.c.cfg, turned)
                            self.assertEqual(h.c.kind, FIX_WORK)
                            h.save()
                            self.assertEqual(len(h.saves), 1)
                            h("ok")
                            self.assertEqual(h.at, (MENU, "get_ready", SETTINGS))

    def test_start_on_a_settings_field_does_nothing(self):
        for field in SETTINGS_FIELDS:
            with self.subTest(field=field):
                h = Hand().to_field(field)
                h("start", ("release", "start"))
                self.assertEqual(h.at, (MENU, field, SETTINGS))
                self.assertIsNone(h.c.workout)


class OkInSettingsTest(unittest.TestCase):
    def test_ok_walks_the_fields_then_returns_to_the_last_used_type(self):
        for kind in TYPES:
            for turn in (0, 1):
                with self.subTest(kind=kind, turn=turn):
                    h = Hand(kind=kind).to_settings()
                    seen = []
                    while h.c.field != "type":
                        seen.append(h.c.field)
                        if turn:
                            h(turn)
                        h("ok")
                    self.assertEqual(seen, list(SETTINGS_FIELDS))
                    self.assertEqual(h.at, (MENU, "type", kind))
                    self.assertEqual(h.c.kind, kind)
                    if turn:
                        self.assertEqual(settings_of(h.c.cfg),
                                         {"get_ready": 6, "sound": False, "step": 10,
                                          "skip_with": "start"})

    def test_ok_on_skip_with_after_a_back_out_and_back_in(self):
        h = Hand(kind=FIX_WORK).to_field("step")
        h("back", "ok")                                 # GET READY again
        h("ok", "ok", "ok")
        self.assertEqual(h.c.field, "skip_with")
        h("ok")
        self.assertEqual(h.c.field, "type")
        self.assertEqual(h.c.choice, FIX_WORK)


class SetupBackUnchangedTest(unittest.TestCase):
    def test_summary_back_goes_to_rounds(self):
        for kind in TYPE_FIELDS:
            with self.subTest(kind=kind):
                h = Hand(kind=kind)("ok", *setup_oks(kind))
                self.assertEqual(h.c.screen, SUMMARY)
                h("back")
                self.assertEqual((h.c.screen, h.c.field), (MENU, "rounds"))

    def test_setup_still_steps_back_after_a_visit_to_settings(self):
        h = Hand(kind=TABATA).to_field("sound")
        h("back", 1, "ok", *setup_oks(TABATA)[:-1])     # TABATA: WORK, REST, ROUNDS
        self.assertEqual(h.at, (MENU, "rounds", TABATA))
        h("back")
        self.assertEqual(h.c.field, "rest")
        h("back", "back", "back", "back")               # REST's minutes, WORK's two parts
        self.assertEqual(h.at, (MENU, "type", TABATA))
        h("back")                                       # nowhere further
        self.assertEqual(h.at, (MENU, "type", TABATA))


class WorkoutUnaffectedTest(unittest.TestCase):
    def workout_after_settings(self, kind, skip_with):
        """Leave SETTINGS with BACK after setting SKIP WITH, then pick
        `kind` and start it."""
        h = Hand(kind=kind).to_field("skip_with")
        if skip_with != "ok":
            h(1)
        h("back")
        h.save()
        while h.c.choice != kind:
            h(1)
        h("ok", *setup_oks(kind), "start")
        self.assertEqual(h.c.screen, RUN)
        self.assertEqual(h.c.cfg["skip_with"], skip_with)
        return h

    def test_stop_prompt_and_recap_back(self):
        for kind in TYPES:
            for skip_with in app.SKIP_BUTTONS:
                with self.subTest(kind=kind, skip_with=skip_with):
                    h = self.workout_after_settings(kind, skip_with)
                    self.assertNotIn(h.c.field, SETTINGS_FIELDS)
                    h("back")
                    self.assertEqual(h.c.screen, RUN)
                    self.assertIsNotNone(h.c.stop_until)     # STOP?
                    self.assertTrue(h.c.workout.running)
                    h(RELEASE)
                    self.assertIsNotNone(h.c.stop_until)     # a release isn't the second BACK
                    h("back")
                    self.assertEqual(h.c.screen, RECAP)
                    self.assertTrue(h.c.workout.stopped)
                    h(RELEASE, "back")
                    self.assertEqual(h.at, (MENU, "type", kind))   # not SETTINGS

    def test_stop_prompt_answered_no_and_expired(self):
        h = self.workout_after_settings(FIX_WORK, "ok")
        h("back", "ok")                                   # any other button answers no
        self.assertEqual((h.c.screen, h.c.stop_until), (RUN, None))
        h("back")
        h.now += app.STOP_CONFIRM + 0.1
        h.c.update(h.now)
        self.assertIsNone(h.c.stop_until)                 # ran out
        h("back")
        self.assertEqual(h.c.screen, RUN)                 # a new STOP?, not a stop
        self.assertIsNotNone(h.c.stop_until)

    def test_recap_back_after_a_natural_end(self):
        h = Hand(kind=FIX_WORK, get_ready=0)
        h.c.cfg["types"][FIX_WORK].update(work=5, rounds=1)
        h.to_field("get_ready")("back", -1, "ok", *setup_oks(FIX_WORK), "start")
        self.assertEqual(h.c.screen, RUN)
        h.now += 10
        h.c.update(h.now)
        self.assertEqual(h.c.screen, RECAP)
        h("back")
        self.assertEqual(h.at, (MENU, "type", FIX_WORK))


# --- a seeded random walk through the setup ----------------------------------

class RandomSetupTest(unittest.TestCase):
    def test_random_sessions_follow_the_spec(self):
        rng = random.Random(20261006)
        values = list(ODD) + [1, 5, 20, 60, 61, 90, 600, 3540]
        for run in range(150):
            kind, step = rng.choice(TYPES), rng.choice(STEPS)
            h = Hand(kind=kind, step=step, skip_with=rng.choice(app.SKIP_BUTTONS),
                     work=rng.choice(values), rest=rng.choice(values),
                     rounds=rng.choice([1, 2, 8, 99, None]))
            others = copy.deepcopy({k: v for k, v in h.c.cfg["types"].items() if k != kind})
            model = dict(h.c.cfg["types"][kind])
            line, i, anchor, log = line_of(kind), 0, None, []
            for _ in range(70):
                where = line[i]
                choices = ["ok", "back", "release"]
                if where != SUMMARY:
                    choices.append("start")
                if where != ("type", kind):
                    choices += ["live", "live", "held"]
                pick = rng.choice(choices)
                if pick == "release":
                    event = ("release", rng.choice(BUTTONS))
                elif pick == "live":
                    event = rng.choice((1, -1, 2, -2, 3))
                elif pick == "held":
                    event = Held(rng.choice((2, 3, -3, 5, -7, 59, -60, 61, -61, 120)))
                else:
                    event = pick
                log.append(event if not isinstance(event, Held) else "Held(%d)" % event.delta)
                h(event, gap=rng.choice((0.09, 0.3, 0.5, 0.77, 1.0, 1.3, 2.0)))

                # The model.
                if event == "ok":
                    i = min(i + 1, len(line) - 1)
                elif event == "back":
                    i = max(i - 1, 0)
                where = line[i]
                timed = isinstance(where, tuple) and where[0] in TIME_FIELDS
                if isinstance(event, (int, Held)):
                    delta = event if isinstance(event, int) else event.delta
                    if timed:
                        field, part = where
                        detent = spec_minute if part == MINUTES else spec_second
                        model[field] = spec_turn(detent, model[field], delta, step)
                        anchor = (h.now, True)
                    elif where == "rounds":
                        model["rounds"] = spec_rounds(model["rounds"], delta)
                elif event in ("ok", "back"):
                    anchor = (h.now, False) if timed else None

                msg = "run %d (%s, step %d): %s" % (run, kind, step, log)
                self.assertEqual(h.spot, where, msg)
                self.assertEqual(h.c.cfg["types"][kind], model, msg)
                self.assertEqual({k: v for k, v in h.c.cfg["types"].items() if k != kind},
                                 others, msg)
                if timed and anchor is not None:
                    at, detent = anchor
                    for dt in (0.0, 0.3, 0.7, 1.2, 1.7, 2.2):
                        self.assertEqual(hidden(h.c, at + dt),
                                         spec_hidden(where[1], dt, detent),
                                         "%s, %.1f s after" % (msg, dt))
                elif not timed and h.c.screen in (MENU, SUMMARY):
                    self.assertEqual(app.render(h.c, h.now + 0.7),
                                     app.render(h.c, h.now + 0.2), msg)


if __name__ == "__main__":
    unittest.main()
