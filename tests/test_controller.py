"""Controller: the menu flow, the wheel, SETTINGS, the workout's buttons,
SKIP WITH, skips, the STOP? prompt, sounds, recap paging and saving."""
import copy
import dataclasses
import json
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import tearDownModule  # noqa: E402,F401  (first: guards the real settings)
from support import T0, running, spot, stats, to_summary  # noqa: E402
import app  # noqa: E402
from app import (FIX_REST, FIX_WORK, MINUTES, RECAP, MENU, REST, RUN,  # noqa: E402
                 SECONDS, SETTINGS, SUMMARY, TABATA, TIME_FIELDS, TYPE_FIELDS, WORK,
                 Controller, Wheel)


class HandController(Controller):
    """A Controller whose wheel turns, when press() is given no time, come
    0.3 s apart like a hand turning it (turns at one instant in opposite
    directions would look like a contact bounce)."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self._hand_clock = T0

    def next_turn_at(self):
        self._hand_clock += 0.3
        return self._hand_clock


def ctrl(**cfg):
    c = app.default_config()
    c.update(cfg)
    return HandController(c)


def press(c, *events, at=None):
    """Buttons and wheel turns (ints) at `at`; without it, buttons at T0 and
    wheel turns at c.next_turn_at()."""
    for e in events:
        if isinstance(e, int):
            turned_at = c.next_turn_at() if at is None else at
            c.handle(Wheel(e, turned_at, False), turned_at)
        else:
            c.handle(e, T0 if at is None else at)
    return c


def where(c):
    return c.screen, c.field


class MenuFlowTest(unittest.TestCase):
    def test_starts_on_type_with_the_last_used_type(self):
        c = ctrl(last_type=FIX_WORK)
        self.assertEqual((where(c), c.choice), ((MENU, "type"), FIX_WORK))

    def test_type_wheel_wraps_through_settings(self):
        c = ctrl()
        press(c, 1)
        self.assertEqual(c.choice, FIX_REST)
        press(c, 2)
        self.assertEqual(c.choice, SETTINGS)
        press(c, 1)
        self.assertEqual(c.choice, TABATA)
        press(c, -1)
        self.assertEqual(c.choice, SETTINGS)

    def test_fields_per_type(self):
        work, rest = [("work", MINUTES), ("work", SECONDS)], [("rest", MINUTES), ("rest", SECONDS)]
        for kind, fields in ((TABATA, work + rest + ["rounds"]),
                             (FIX_REST, rest + ["rounds"]),
                             (FIX_WORK, work + ["rounds"])):
            with self.subTest(kind):
                c = ctrl(last_type=kind)
                seen = []
                press(c, "ok")
                while c.screen == MENU:
                    seen.append(spot(c))
                    press(c, "ok")
                self.assertEqual(seen, fields)
                self.assertEqual(c.screen, SUMMARY)

    def test_choosing_a_type_makes_it_the_last_type(self):
        c = press(ctrl(), 2, "ok")
        self.assertEqual((c.kind, spot(c)), (FIX_WORK, ("work", MINUTES)))

    def test_wheel_changes_the_current_field(self):
        c = press(ctrl(), "ok", 2, "ok", -1, "ok", "ok", -1, "ok")
        for i in range(8):                          # slow clicks: one step each
            press(c, -1, at=T0 + i)
        self.assertEqual(c.cfg["types"][TABATA], {"work": 135, "rest": 5, "rounds": None})
        self.assertEqual(c.cfg["types"][FIX_REST], app.default_config()["types"][FIX_REST])

    def test_time_step_setting_is_used(self):
        c = press(ctrl(step=15), "ok", "ok", 1)
        self.assertEqual(c.cfg["types"][TABATA]["work"], 30)
        c = press(ctrl(step=1), "ok", "ok", 1, 1, -1, -1, -1)
        self.assertEqual(c.cfg["types"][TABATA]["work"], 19)

    def test_defaults_per_type(self):
        types = app.default_config()["types"]
        self.assertEqual((types[TABATA]["work"], types[TABATA]["rest"], types[TABATA]["rounds"]),
                         (20, 10, 8))
        self.assertEqual((types[FIX_REST]["rest"], types[FIX_REST]["rounds"]), (90, 5))
        self.assertEqual((types[FIX_WORK]["work"], types[FIX_WORK]["rounds"]), (45, 5))

    def test_start_and_wheel_do_nothing_outside_their_screens(self):
        c = press(ctrl(), "start")
        self.assertEqual(where(c), (MENU, "type"))
        press(c, *to_summary(), 5, "ok")
        self.assertEqual((c.screen, c.cfg["types"][TABATA]["rounds"]), (SUMMARY, 8))


class TimePartsTest(unittest.TestCase):
    """WORK and REST are set in two parts, minutes then seconds (SPEC 4)."""

    def open(self, kind, field):
        c = press(ctrl(last_type=kind), "ok")
        while c.field != field:
            press(c, "ok")
        return c

    def time_fields(self):
        for kind, fields in TYPE_FIELDS.items():
            for i, field in enumerate(fields):
                if field in TIME_FIELDS:
                    yield kind, field, (("type", kind) if i == 0 else (fields[i - 1], SECONDS))

    def test_a_time_opens_on_its_minutes_and_ok_moves_to_its_seconds(self):
        for kind, field, _ in self.time_fields():
            with self.subTest(kind=kind, field=field):
                c = self.open(kind, field)
                self.assertEqual(spot(c), (field, MINUTES))
                press(c, "ok")
                self.assertEqual(spot(c), (field, SECONDS))

    def test_back_goes_from_the_seconds_to_the_minutes_then_to_the_field_before(self):
        for kind, field, before in self.time_fields():
            with self.subTest(kind=kind, field=field):
                c = press(self.open(kind, field), "ok", "back")
                self.assertEqual(spot(c), (field, MINUTES))
                press(c, "back")
                self.assertEqual((spot(c), c.choice, c.kind), (before, kind, kind))

    def test_back_into_a_time_lands_on_its_seconds(self):
        for kind, fields in TYPE_FIELDS.items():
            with self.subTest(kind=kind):
                c = press(ctrl(last_type=kind), *to_summary(kind), "back")
                self.assertEqual(spot(c), "rounds")
                press(c, "back")
                self.assertEqual(spot(c), (fields[-2], SECONDS))
        c = press(ctrl(), "ok", "ok", "ok")               # WORK's seconds, then REST
        self.assertEqual(spot(c), ("rest", MINUTES))
        press(c, "back")
        self.assertEqual(spot(c), ("work", SECONDS))

    def test_the_wheel_sets_the_part_on_screen(self):
        c = press(ctrl(), "ok", 2)                        # minutes: 0:20 -> 2:20
        self.assertEqual(c.cfg["types"][TABATA]["work"], 140)
        press(c, "ok", -1)                                # seconds: 2:15
        self.assertEqual(c.cfg["types"][TABATA]["work"], 135)
        press(c, "back", -2)                              # minutes again: 0:15
        self.assertEqual(c.cfg["types"][TABATA]["work"], 15)


class WheelTest(unittest.TestCase):
    """Every detent moves the value exactly one step, however fast the wheel
    turns, and a held burst moves all of its detents."""

    def turn(self, c, detents, gap, start=T0, direction=1):
        seen = []
        for i in range(detents):
            press(c, direction, at=start + i * gap)
            seen.append(c.cfg["types"][c.kind].get(c.field))
        return seen

    def work_field(self, part, step=5, **values):
        c = ctrl(step=step)
        c.cfg["types"][TABATA].update(values)
        return press(c, "ok", *(["ok"] if part == SECONDS else []))

    def work(self, c):
        return c.cfg["types"][TABATA]["work"]

    def test_the_seconds_move_by_the_time_step(self):
        c = self.work_field(SECONDS, work=5)
        self.assertEqual(self.turn(c, 6, gap=0.3), [10, 15, 20, 25, 30, 35])

    def test_fast_turning_never_speeds_up(self):
        for gap in (0.3, 0.05, 0.01):
            with self.subTest(gap=gap):
                c = self.work_field(SECONDS, work=5)
                self.assertEqual(self.turn(c, 6, gap=gap), [10, 15, 20, 25, 30, 35])
                c = self.work_field(MINUTES)
                self.assertEqual(self.turn(c, 15, gap=gap), [m * 60 + 20 for m in range(1, 16)])

    def test_a_held_burst_moves_all_its_detents(self):
        c = self.work_field(SECONDS)                       # 0:20
        c.handle(Wheel(5, 501.118, True), T0)
        self.assertEqual(self.work(c), 45)
        c.handle(Wheel(-3, 502.118, True), T0)
        self.assertEqual(self.work(c), 30)
        c = self.work_field(MINUTES)
        c.handle(Wheel(5, 501.118, True), T0)
        self.assertEqual(self.work(c), 5 * 60 + 20)

    def test_a_held_burst_in_a_fast_turn_counts_like_live_detents(self):
        c = self.work_field(SECONDS, work=5)
        self.turn(c, 4, gap=0.03, start=500.5)             # 0:25
        c.handle(Wheel(5, 501.118, True), T0)              # 0:50
        self.assertEqual(self.work(c), 50)
        c.handle(Wheel(1, 501.125, False), T0)
        c.handle(Wheel(1, 501.15, False), T0)              # 0:55, then wraps to 0:05
        self.assertEqual(self.work(c), 5)

    def test_a_bounce_against_the_turn_is_ignored(self):
        for part, after in ((SECONDS, 40), (MINUTES, 4 * 60 + 20)):
            with self.subTest(part):
                c = self.work_field(part)
                for d, t in [(1, 0), (1, 0.03), (1, 0.06), (-1, 0.07), (1, 0.09)]:
                    c.handle(Wheel(d, T0 + t, False), T0 + t)
                self.assertEqual(self.work(c), after)

    def test_bounces_are_timed_by_the_bars_clock_when_it_is_there(self):
        c = self.work_field(SECONDS)
        for i, d in enumerate((1, 1, -1)):                 # turned slowly, arriving together
            c.handle(Wheel(d, 500.0 + 0.3 * i, False), T0)
        self.assertEqual(self.work(c), 25)

    def test_a_clock_stepping_back_is_no_bounce(self):
        c = self.work_field(SECONDS)
        c.handle(Wheel(1, 500.0, False), T0)
        c.handle(Wheel(-1, 499.99, False), T0)             # the bar's clock jumped back
        self.assertEqual(self.work(c), 20)

    def test_turning_the_seconds_down_wraps_at_the_time_step(self):
        c = self.work_field(SECONDS, work=20)
        self.assertEqual(self.turn(c, 6, gap=0.3, direction=-1), [15, 10, 5, 55, 50, 45])

    def test_turning_the_minutes_down_reaches_the_time_step_then_wraps(self):
        c = self.work_field(MINUTES, work=600)
        seen = self.turn(c, 12, gap=0.05, direction=-1)
        self.assertEqual(seen, [m * 60 for m in range(9, 0, -1)] + [5, 59 * 60 + 5, 58 * 60 + 5])

    def test_turning_the_minutes_up_from_59_wraps_to_0(self):
        c = self.work_field(MINUTES, work=59 * 60 + 3)
        self.assertEqual(self.turn(c, 2, gap=0.3), [5, 65])          # below the step: to it
        c = self.work_field(MINUTES, work=59 * 60 + 30)
        self.assertEqual(self.turn(c, 2, gap=0.3), [30, 90])

    def test_a_held_burst_across_0_minutes_counts_like_its_detents_one_by_one(self):
        for step in app.STEPS:
            for start, delta in ((58 * 60, 3), (58 * 60 + 3, 3), (60, -3), (63, -3),
                                 (3, 60), (3, -60), (30, 61), (30, -61)):
                with self.subTest(step=step, start=app.fmt_time(start), delta=delta):
                    live = self.work_field(MINUTES, step=step, work=start)
                    self.turn(live, abs(delta), gap=0.3, direction=1 if delta > 0 else -1)
                    held = self.work_field(MINUTES, step=step, work=start)
                    held.handle(Wheel(delta, 501.118, True), T0)
                    self.assertEqual(self.work(held), self.work(live))

    def test_with_a_one_second_step_the_seconds_wrap_at_0_01(self):
        c = ctrl(step=1)
        c.cfg["types"][TABATA]["work"] = 4
        press(c, "ok", "ok")
        self.assertEqual(self.turn(c, 5, gap=0.3, direction=-1), [3, 2, 1, 59, 58])

    def test_a_saved_time_below_the_step_snaps_up_when_its_seconds_turn(self):
        for direction in (1, -1):
            c = self.work_field(SECONDS, work=3)
            self.assertEqual(self.turn(c, 1, gap=0.3, direction=direction), [5])

    def test_the_minutes_keep_a_saved_time_below_the_step_until_they_reach_0(self):
        c = self.work_field(MINUTES, work=3)
        self.assertEqual(self.turn(c, 2, gap=0.3), [63, 123])
        self.assertEqual(self.turn(c, 2, gap=0.3, start=T0 + 1, direction=-1), [63, 5])
        c = self.work_field(MINUTES, work=3)
        self.assertEqual(self.turn(c, 2, gap=0.3, direction=-1), [59 * 60 + 3, 58 * 60 + 3])
        self.assertEqual(self.turn(c, 2, gap=0.3, start=T0 + 1), [59 * 60 + 3, 5])

    def test_every_time_field_goes_down_to_the_chosen_time_step(self):
        fields = ((TABATA, "work"), (TABATA, "rest"), (FIX_REST, "rest"), (FIX_WORK, "work"))
        for kind, field in fields:
            for step in app.STEPS:
                with self.subTest(kind=kind, field=field, step=step):
                    c = ctrl(step=step, last_type=kind)
                    c.cfg["types"][kind][field] = 120
                    press(c, "ok")
                    while c.field != field:
                        press(c, "ok")
                    seen = self.turn(c, 2, gap=0.3, direction=-1)          # minutes
                    self.assertEqual(seen, [60, step])
                    press(c, "ok")                                         # seconds
                    self.assertEqual(self.turn(c, 1, gap=0.3, direction=-1), [60 - step])

    def test_raising_the_step_keeps_a_lower_time_until_it_is_turned(self):
        c = press(ctrl(step=1), "ok", "ok", *[-1] * 17)              # WORK 0:20 -> 0:03
        self.assertEqual(self.work(c), 3)
        press(c, "back", "back", -1, "ok", "ok", "ok", 1, "ok", "ok")   # SETTINGS: step 1 -> 5
        self.assertEqual((c.cfg["step"], where(c), c.choice), (5, (MENU, "type"), TABATA))
        press(c, "ok", "ok")
        self.assertEqual((spot(c), self.work(c)), (("work", SECONDS), 3))
        press(c, -1)
        self.assertEqual(self.work(c), 5)                            # snaps up to the new step

    def test_rounds_and_type_move_one_per_detent_however_fast(self):
        c = press(ctrl(), *to_summary()[:-1])
        self.assertEqual(c.field, "rounds")
        self.turn(c, 20, gap=0.02)
        self.assertEqual(c.cfg["types"][TABATA]["rounds"], 28)
        c = ctrl()
        self.turn(c, 9, gap=0.02)
        self.assertEqual(c.choice, FIX_REST)                     # 9 steps around 4 entries


class BounceBoundaryTest(unittest.TestCase):
    """BOUNCE_MS exactly, on timestamps like the bar's: whole ms since the
    epoch, in seconds. Many starting stamps, because whether float seconds
    land just above or below a whole ms depends on the stamp."""
    EPOCH_MS = 1791119372191

    def stamps(self):
        return range(self.EPOCH_MS, self.EPOCH_MS + 300)

    def turn(self, c, ms, delta=1, held=False):
        c.handle(Wheel(delta, ms / 1000, held), T0)

    def fields(self):
        """(name, controller on that field, its value) for ROUNDS 8 and WORK's
        seconds 0:20."""
        yield ("rounds", lambda: press(ctrl(), *to_summary()[:-1]),
               lambda c: c.cfg["types"][TABATA]["rounds"])
        yield ("work seconds", lambda: press(ctrl(), "ok", "ok"),
               lambda c: c.cfg["types"][TABATA]["work"])

    def test_a_turn_back_79_ms_after_the_last_is_a_bounce_80_and_81_are_not(self):
        for name, make, value in self.fields():
            for gap, bounce in ((79, True), (80, False), (81, False)):
                for start in self.stamps():
                    c = make()
                    before = value(c)
                    self.turn(c, start)
                    after_one = value(c)
                    self.turn(c, start + gap, delta=-1)
                    want = after_one if bounce else before
                    self.assertEqual(value(c), want, (name, gap, start))

    def test_arrival_stamps_with_fractions_of_a_ms_round_to_the_nearest_ms(self):
        # Without the bar's clock the app stamps arrival with time.time().
        base = 1791119372.1234567
        for gap_ms, rounds in ((79.4, 9), (79.6, 8)):
            c = press(ctrl(), *to_summary()[:-1])               # ROUNDS 8
            c.handle(Wheel(1, base, False), T0)
            c.handle(Wheel(-1, base + gap_ms / 1000, False), T0)
            self.assertEqual(c.cfg["types"][TABATA]["rounds"], rounds, gap_ms)


class HeldBurstPerFieldTest(unittest.TestCase):
    """Every field moves one step per detent of a held burst."""

    def turn_with_burst(self, c, live_before, burst, live_after):
        # Live detents 0.03 s apart, the bar's held burst, then live detents
        # again.
        for i in range(live_before):
            c.handle(Wheel(1, 500.5 + i * 0.03, False), T0)
        c.handle(Wheel(burst, 501.118, True), T0)
        for i in range(live_after):
            c.handle(Wheel(1, 501.125 + i * 0.025, False), T0)
        return c

    def rounds_field(self, rounds):
        c = ctrl()
        c.cfg["types"][TABATA]["rounds"] = rounds
        return press(c, *to_summary()[:-1])

    def test_rounds_move_with_every_detent_of_a_burst(self):
        c = self.turn_with_burst(self.rounds_field(8), 4, 5, 3)
        self.assertEqual(c.cfg["types"][TABATA]["rounds"], 20)

    def test_rounds_burst_wraps_through_unlimited(self):
        c = self.turn_with_burst(self.rounds_field(95), 4, 5, 3)  # 99, then ∞, 1 ...
        self.assertEqual(c.cfg["types"][TABATA]["rounds"], 7)

    def test_a_large_burst_alone_moves_rounds(self):
        c = self.rounds_field(8)
        c.handle(Wheel(5, 501.118, True), T0)
        self.assertEqual(c.cfg["types"][TABATA]["rounds"], 13)

    def test_type_moves_with_every_detent_of_a_burst(self):
        c = self.turn_with_burst(ctrl(), 2, 5, 0)       # 7 steps around 4 entries
        self.assertEqual(c.choice, SETTINGS)

    def test_settings_move_with_every_detent_of_a_burst(self):
        c = press(ctrl(), -1, "ok")                     # TYPE wraps back to SETTINGS
        self.assertEqual(c.field, "get_ready")
        self.turn_with_burst(c, 2, 5, 1)
        self.assertEqual(c.cfg["get_ready"], 5 + 8)
        press(c, "ok", "ok")
        self.turn_with_burst(c, 2, 3, 0)                # 2 live steps: 5 -> 15; burst of 3 wraps to 1, 5, 10
        self.assertEqual(c.cfg["step"], 10)
        press(c, "ok")
        self.turn_with_burst(c, 2, 3, 0)                # 2 live flips, then 3 held: 5 flips
        self.assertEqual(c.cfg["skip_with"], "start")

    def test_work_and_rest_move_with_every_detent_of_a_burst(self):
        c = press(ctrl(), "ok")                         # WORK's minutes, 0:20
        self.turn_with_burst(c, 4, 5, 0)
        self.assertEqual(c.cfg["types"][TABATA]["work"], 9 * 60 + 20)
        press(c, "ok")                                  # its seconds
        self.turn_with_burst(c, 2, 3, 0)
        self.assertEqual(c.cfg["types"][TABATA]["work"], 9 * 60 + 45)
        press(c, "ok", "ok")                            # REST's seconds, 0:10
        self.turn_with_burst(c, 4, 5, 0)
        self.assertEqual(c.cfg["types"][TABATA]["rest"], 55)

    def test_a_negative_burst_wraps_rounds_back_through_unlimited(self):
        c = self.rounds_field(3)
        c.handle(Wheel(-5, 501.118, True), T0)           # 2, 1, ∞, 99, 98
        self.assertEqual(c.cfg["types"][TABATA]["rounds"], 98)

    def test_a_bounce_is_ignored_on_rounds_type_and_settings(self):
        c = self.rounds_field(8)
        for d, t in [(1, 0), (1, 0.03), (1, 0.06), (-1, 0.07), (1, 0.09)]:
            c.handle(Wheel(d, 500 + t, False), T0)
        self.assertEqual(c.cfg["types"][TABATA]["rounds"], 12)
        c = self.rounds_field(8)
        c.handle(Wheel(3, 500.0, True), T0)
        c.handle(Wheel(-1, 500.05, False), T0)          # bounce after a held burst
        self.assertEqual(c.cfg["types"][TABATA]["rounds"], 11)
        c = ctrl()
        c.handle(Wheel(1, 500.0, False), T0)
        c.handle(Wheel(-1, 500.03, False), T0)
        self.assertEqual(c.choice, FIX_REST)
        c = press(ctrl(), -1, "ok")                     # GET READY
        c.handle(Wheel(1, 500.0, False), T0)
        c.handle(Wheel(-1, 500.03, False), T0)
        self.assertEqual(c.cfg["get_ready"], 6)

    def test_a_held_burst_against_the_turn_is_no_bounce(self):
        c = self.rounds_field(8)
        c.handle(Wheel(1, 500.0, False), T0)
        c.handle(Wheel(-2, 500.02, True), T0)
        self.assertEqual(c.cfg["types"][TABATA]["rounds"], 7)

    def test_settings_bursts_clamp_and_flip_per_detent(self):
        c = press(ctrl(sound=True), -1, "ok")           # GET READY
        c.handle(Wheel(20, 500.0, True), T0)
        self.assertEqual(c.cfg["get_ready"], 15)
        c.handle(Wheel(-30, 501.0, True), T0)
        self.assertEqual(c.cfg["get_ready"], 0)
        press(c, "ok")                                  # SOUND
        c.handle(Wheel(3, 502.0, True), T0)
        self.assertFalse(c.cfg["sound"])
        c.handle(Wheel(2, 503.0, True), T0)
        self.assertFalse(c.cfg["sound"])
        c.handle(Wheel(-3, 504.0, True), T0)
        self.assertTrue(c.cfg["sound"])

    def test_recap_still_takes_a_held_burst_of_one_or_two(self):
        for burst, page in ((1, "rest"), (2, "rounds"), (-1, "total"), (-2, "rounds"),
                            (3, None), (-3, None)):
            with self.subTest(burst=burst):
                c = press(ctrl(), *to_summary(), "start")
                c.workout.stop(T0 + 1)
                c.update(T0 + 1)
                c.handle(Wheel(burst, 500.0, True), T0 + 1)
                self.assertEqual(c.page, page)


class SettingsTest(unittest.TestCase):
    def open_settings(self, **cfg):
        c = ctrl(**cfg)
        while c.choice != SETTINGS:
            press(c, 1)
        return press(c, "ok")

    def test_settings_fields_and_return_to_type(self):
        c = self.open_settings()
        self.assertEqual(c.field, "get_ready")
        press(c, -2, "ok", 1, "ok", 1, "ok", 1, "ok")
        self.assertEqual((c.cfg["get_ready"], c.cfg["sound"], c.cfg["step"], c.cfg["skip_with"]),
                         (3, False, 10, "start"))
        self.assertEqual((where(c), c.choice), ((MENU, "type"), TABATA))

    def test_skip_with_flips_on_each_detent_without_a_tick(self):
        c = press(self.open_settings(sound=True), "ok", "ok", "ok")
        seen = []
        for delta in (1, 1, 2, -1, -2, 3):
            press(c, delta)
            seen.append(c.cfg["skip_with"])
        self.assertEqual(seen, ["start", "ok", "ok", "start", "start", "ok"])
        self.assertEqual(c.sounds, [])                  # unlike SOUND, no preview

    def test_skip_with_takes_every_detent_of_a_held_burst(self):
        c = press(self.open_settings(), "ok", "ok", "ok")
        for i, (burst, after) in enumerate(((3, "start"), (2, "start"), (-5, "ok"), (-2, "ok"))):
            c.handle(Wheel(burst, 500.0 + i, True), T0)
            self.assertEqual(c.cfg["skip_with"], after, burst)

    def test_skip_with_is_saved_on_the_next_press(self):
        c = press(self.open_settings(), "ok", "ok", "ok", 1)
        self.assertEqual((c.cfg["skip_with"], c.unsaved(), c.save_due), ("start", True, False))
        press(c, "ok")
        self.assertTrue(c.save_due)

    def test_ranges(self):
        c = press(self.open_settings(), 20)
        self.assertEqual(c.cfg["get_ready"], 15)
        press(c, -30)
        self.assertEqual(c.cfg["get_ready"], 0)
        press(c, "ok", 2)
        self.assertTrue(c.cfg["sound"])                 # two detents: toggled twice
        press(c, "ok", -1)
        self.assertEqual(c.cfg["step"], 1)
        press(c, -1)
        self.assertEqual(c.cfg["step"], 15)             # wraps 1 -> 15


class WorkoutButtonsTest(unittest.TestCase):
    def test_start_uses_the_saved_settings(self):
        c = running(FIX_REST, get_ready=0, rest=45, rounds=None)
        w = c.workout
        self.assertEqual(c.screen, RUN)
        self.assertEqual((w.kind, w.rest, w.rounds, w.phase), (FIX_REST, 45, None, WORK))

    def test_ok_advances_open_phase_and_start_pauses(self):
        c = running(FIX_REST, get_ready=0)
        press(c, "ok", at=T0 + 30)
        self.assertEqual(c.workout.phase, app.REST)
        press(c, "start", at=T0 + 32)
        self.assertTrue(c.workout.paused)
        press(c, "start", at=T0 + 40)
        self.assertFalse(c.workout.paused)

    def test_wheel_is_ignored_during_a_workout(self):
        c = running()
        press(c, 3, at=T0 + 1)
        self.assertEqual(c.cfg["types"][TABATA]["work"], 20)

    def test_back_twice_within_three_seconds_stops(self):
        c = running()
        press(c, "back", at=T0 + 8)
        self.assertEqual(c.stop_until, T0 + 11)
        press(c, "back", at=T0 + 10.9)
        self.assertEqual(c.screen, RECAP)
        self.assertTrue(c.workout.stopped)
        self.assertAlmostEqual(c.workout.stats.work_seconds, 5.9)

    def test_stop_prompt_expires_without_touching_the_timer(self):
        c = running()
        press(c, "back", at=T0 + 8)
        c.update(T0 + 11)
        self.assertIsNone(c.stop_until)
        press(c, "back", at=T0 + 12)
        self.assertEqual((c.screen, c.stop_until), (RUN, T0 + 15))
        self.assertEqual(c.workout.display_seconds(T0 + 12), 13)

    def test_other_buttons_cancel_the_prompt(self):
        c = running()
        press(c, "back", at=T0 + 8)
        press(c, "start", at=T0 + 9)
        self.assertIsNone(c.stop_until)
        self.assertTrue(c.workout.paused)
        press(c, "back", at=T0 + 9.5)
        self.assertEqual(c.screen, RUN)

    def test_finishing_naturally_then_repeat_or_menu(self):
        c = running(get_ready=0, rounds=1)
        c.update(T0 + 20)
        self.assertEqual(c.screen, RECAP)
        self.assertFalse(c.workout.stopped)
        press(c, "ok", 2, at=T0 + 21)
        self.assertEqual(c.screen, RECAP)
        press(c, "start", at=T0 + 22)
        self.assertEqual((c.screen, c.workout.phase), (RUN, WORK))
        c.update(T0 + 42)
        press(c, "back", at=T0 + 43)
        self.assertEqual((where(c), c.choice), ((MENU, "type"), TABATA))

    def test_summary_back_returns_to_the_last_field(self):
        c = ctrl(last_type=FIX_WORK)
        press(c, *to_summary(FIX_WORK))
        self.assertEqual(c.screen, SUMMARY)
        press(c, "back")
        self.assertEqual(where(c), (MENU, "rounds"))


class SkipWithTest(unittest.TestCase):
    """SKIP WITH picks which of OK and START skips during a workout, STOP?
    prompt included; the other one pauses. The menu, summary and recap keep
    their buttons (SPEC 3)."""
    MODES = (("ok", "ok", "start"), ("start", "start", "ok"))   # (setting, skip, pause)

    def test_the_skip_button_ends_every_phase_in_every_type(self):
        for skip_with, skip, _ in self.MODES:
            for kind in app.TYPES:
                with self.subTest(skip_with=skip_with, kind=kind):
                    c = running(kind, skip_with=skip_with, rounds=2)
                    seen = []
                    for i in range(1, 5):
                        c.update(T0 + i)
                        c.sounds.clear()
                        press(c, skip, at=T0 + i)
                        w = c.workout
                        seen.append((w.phase, w.round, w.paused, list(c.sounds)))
                    finish, done = [app.SOUND_FINISH], [app.SOUND_COMPLETED]
                    self.assertEqual(seen, [(WORK, 1, False, finish), (app.REST, 1, False, finish),
                                            (WORK, 2, False, finish), (app.DONE, 2, False, done)])
                    s = c.workout.stats
                    self.assertEqual((s.work_seconds, s.rest_seconds, s.rounds_completed), (2, 1, 2))
                    self.assertEqual((c.screen, c.workout.stopped), (RECAP, False))

    def test_the_pause_button_pauses_and_resumes(self):
        for skip_with, _, pause in self.MODES:
            with self.subTest(skip_with=skip_with):
                c = running(get_ready=0, skip_with=skip_with)
                press(c, pause, at=T0 + 2)
                self.assertTrue(c.workout.paused)
                press(c, pause, at=T0 + 10)
                self.assertFalse(c.workout.paused)
                self.assertEqual((c.workout.phase, c.workout.display_seconds(T0 + 10)), (WORK, 18))

    def test_paused_the_skip_button_is_ignored_and_the_pause_button_resumes(self):
        for skip_with, skip, pause in self.MODES:
            with self.subTest(skip_with=skip_with):
                c = running(get_ready=0, skip_with=skip_with)
                press(c, pause, at=T0 + 2)
                press(c, skip, at=T0 + 3)
                self.assertEqual((c.workout.phase, c.workout.paused), (WORK, True))
                press(c, pause, at=T0 + 4)
                press(c, skip, at=T0 + 5)
                self.assertEqual((c.workout.phase, c.workout.stats.work_seconds), (app.REST, 3))

    def test_stop_prompt_answered_no_by_the_skip_button_which_then_skips(self):
        for skip_with, skip, _ in self.MODES:
            with self.subTest(skip_with=skip_with):
                c = running(get_ready=0, skip_with=skip_with)
                press(c, "back", at=T0 + 5)
                press(c, skip, at=T0 + 6)
                self.assertIsNone(c.stop_until)
                self.assertEqual((c.screen, c.workout.phase, c.workout.paused), (RUN, app.REST, False))

    def test_stop_prompt_answered_no_by_the_pause_button_which_then_pauses(self):
        for skip_with, _, pause in self.MODES:
            with self.subTest(skip_with=skip_with):
                c = running(get_ready=0, skip_with=skip_with)
                press(c, "back", at=T0 + 5)
                press(c, pause, at=T0 + 6)
                self.assertIsNone(c.stop_until)
                self.assertEqual((c.screen, c.workout.phase, c.workout.paused), (RUN, WORK, True))
                press(c, "back", at=T0 + 6.5)              # a new prompt, not a stop
                self.assertEqual((c.screen, c.workout.stopped), (RUN, False))

    def test_stop_prompt_while_paused(self):
        for skip_with, skip, pause in self.MODES:
            with self.subTest(skip_with=skip_with):
                c = running(get_ready=0, skip_with=skip_with)
                press(c, pause, at=T0 + 5)
                press(c, "back", skip, at=T0 + 6)           # "no"; the skip is ignored
                self.assertEqual((c.stop_until, c.workout.phase, c.workout.paused),
                                 (None, WORK, True))
                press(c, "back", pause, at=T0 + 7)          # "no"; resumed
                self.assertEqual((c.stop_until, c.workout.phase, c.workout.paused),
                                 (None, WORK, False))

    def test_back_twice_still_stops(self):
        c = running(get_ready=0, skip_with="start")
        press(c, "back", "back", at=T0 + 5)
        self.assertEqual((c.screen, c.workout.stopped), (RECAP, True))

    def test_menu_summary_and_recap_keep_their_buttons(self):
        c = ctrl(skip_with="start")
        press(c, "start")                                   # menu: nothing to start
        self.assertEqual((where(c), c.choice), ((MENU, "type"), TABATA))
        press(c, *to_summary())                             # OK confirms each field
        self.assertEqual(c.screen, SUMMARY)
        press(c, "ok")                                      # summary: OK does nothing
        self.assertEqual(c.screen, SUMMARY)
        press(c, "start", at=T0)                            # START starts
        self.assertEqual((c.screen, c.workout.phase), (RUN, app.GET_READY))
        press(c, "back", "back", at=T0 + 1)
        self.assertEqual(c.recap_page(T0 + 2), "work")
        press(c, "ok", at=T0 + 2)                           # recap: OK pages
        self.assertEqual((c.screen, c.page), (RECAP, "rest"))
        press(c, "start", at=T0 + 3)                        # START repeats
        self.assertEqual((c.screen, c.workout.phase, c.workout.stopped),
                         (RUN, app.GET_READY, False))
        press(c, "back", "back", at=T0 + 4)
        press(c, "back", at=T0 + 8)                         # BACK: to TYPE
        self.assertEqual((where(c), c.choice), ((MENU, "type"), TABATA))


# --- SKIP WITH over random input ---------------------------------------------

# Seeded: set to START, the app does during a workout exactly what it does set
# to OK with the OK and START presses swapped, and nothing changes outside a
# workout (SPEC 3, 5.1, 5.4). The field itself turns like SOUND, one flip per
# detent, but never plays a tick.

SEEDS = 200
SWAP = {"ok": "start", "start": "ok"}


def random_cfg(r):
    """Short phases, so the random runs reach every phase and the recap."""
    cfg = app.default_config()
    cfg["last_type"] = r.choice(app.TYPES)
    for kind in app.TYPES:
        cfg["types"][kind] = {"work": r.choice([1, 2, 3, 5, 20]), "rest": r.choice([1, 2, 3, 10]),
                              "rounds": r.choice([1, 2, 3, None])}
    cfg["get_ready"] = r.choice([0, 0, 1, 3, 5])
    cfg["sound"] = r.random() < 0.7
    cfg["step"] = r.choice(app.STEPS)
    return cfg


def random_events(r, n):
    """[(now, event)]: buttons, releases, wheel turns (live and held) and
    plain waits, with gaps from simultaneous to well past a phase."""
    now, out = 1000.0, []
    for _ in range(n):
        now += (r.choice([0.0, 0.01, 0.1, 0.13, 0.3, 0.6, 1.0, 2.5, 4.0])
                if r.random() < 0.95 else r.uniform(5, 40))
        x = r.random()
        if x < 0.30:
            event = "ok"
        elif x < 0.55:
            event = "start"
        elif x < 0.68:
            event = "back"
        elif x < 0.73:
            event = ("release", r.choice(["ok", "back", "start"]))
        elif x < 0.80:
            event = None                                  # time passes
        else:
            held = r.random() < 0.3
            at = math.ceil(now) + r.choice([0, 0.002]) if held else round(now, 3)
            event = Wheel(r.choice([1, -1, 2, -2, 3, -5]), at, held)
        out.append((now, event))
    return out


def snapshot(c, now):
    """Everything the user can see or hear, and what would be saved, apart
    from the SKIP WITH setting itself."""
    w = c.workout
    workout = None if w is None else (
        w.kind, w.work, w.rest, w.rounds, w.get_ready, w.phase, w.round, w.phase_start,
        w.paused_at, w.stopped, dataclasses.astuple(w.stats))
    cfg = {k: v for k, v in c.cfg.items() if k != "skip_with"}
    on_field = c.screen == MENU and c.field == "skip_with"     # shows the setting itself
    shown = None if on_field else json.dumps(app.render(c, now), sort_keys=True)
    return (c.screen, c.field, c.choice, workout, c.stop_until, c.page, list(c.sounds),
            c.save_due, cfg, shown)


class SwappedButtonsTest(unittest.TestCase):
    def test_start_setting_is_the_ok_setting_with_the_buttons_swapped_in_a_workout(self):
        for seed in range(SEEDS):
            r = random.Random(seed)
            cfg = random_cfg(r)
            by_ok = Controller(dict(copy.deepcopy(cfg), skip_with="ok"))
            by_start = Controller(dict(copy.deepcopy(cfg), skip_with="start"))
            for step, (now, event) in enumerate(random_events(r, 150)):
                by_ok.update(now)
                by_start.update(now)
                if by_start.field == "skip_with" and isinstance(event, Wheel):
                    event = None                          # keep each controller's setting
                swapped = event
                if by_start.screen == RUN and event in SWAP:
                    swapped = SWAP[event]                 # what the user means to press
                for c, e in ((by_ok, swapped), (by_start, event)):
                    if e is not None:
                        c.handle(e, now)
                    if c.save_due:                        # as main() does
                        c.saved()
                    c.update(now)
                self.assertEqual(snapshot(by_start, now), snapshot(by_ok, now),
                                 "seed %d, step %d: %r at %.3f" % (seed, step, event, now))
                by_ok.sounds.clear()
                by_start.sounds.clear()
            self.assertEqual((by_ok.cfg["skip_with"], by_start.cfg["skip_with"]), ("ok", "start"))


class SkipWithWheelTest(unittest.TestCase):
    def at_field(self, field):
        cfg = app.default_config()
        cfg["sound"] = field == "skip_with"               # SOUND on: a tick would be heard
        c = Controller(cfg)
        c.choice = app.SETTINGS
        while c.field != field:
            c.handle("ok", 0.0)
        return c

    def test_turns_like_sound_and_never_ticks(self):
        # Live and held detents, bounces included: SKIP WITH flips whenever
        # SOUND does, from OK as SOUND from OFF.
        for seed in range(SEEDS):
            r = random.Random(seed)
            sound, skip_with = self.at_field("sound"), self.at_field("skip_with")
            now = 100.0
            for _ in range(60):
                now += r.choice([0.0, 0.02, 0.05, 0.079, 0.081, 0.12, 0.3, 0.6, 1.0])
                held = r.random() < 0.3
                at = int(now) + 1 + r.choice([0, 0.002, 0.004]) if held else round(now, 3)
                turn = Wheel(r.choice([1, -1, 2, -2, 3, -3, 4]), at, held)
                sound.handle(turn, now)
                skip_with.handle(turn, now)
                self.assertEqual(skip_with.cfg["skip_with"] == "start", sound.cfg["sound"],
                                 (seed, turn))
                self.assertEqual((skip_with.field, skip_with.sounds), ("skip_with", []))
                self.assertTrue(skip_with.cfg["sound"])


# --- skips through the Controller (the Workout's own are in test_timer) ------

def _texts(elements):
    return [e.get("text") for e in elements if isinstance(e, dict)]


class SkipTest(unittest.TestCase):
    def test_burst_of_ok_presses_in_one_loop_pass(self):
        # main() handles every event of a pass with the same `now`.
        c = running(TABATA, get_ready=3, work=5, rest=4, rounds=2)
        for _ in range(3):
            c.handle("ok", T0 + 1)                             # GR -> W1 -> R1 -> W2
        self.assertEqual((c.screen, c.workout.phase, c.workout.round), (RUN, WORK, 2))
        c.handle("ok", T0 + 1)                                 # W2 -> DONE
        self.assertEqual(c.screen, RECAP)
        self.assertFalse(c.workout.stopped)
        self.assertEqual(stats(c.workout), (0, 0, 2))
        self.assertIn(app.SOUND_COMPLETED, c.sounds)
        self.assertIn(app.SOUND_FINISH, c.sounds)
        # main() plays only the most important one
        self.assertEqual(max(c.sounds, key=app.SOUNDS.index), app.SOUND_COMPLETED)

    def test_controller_unlimited_skips_then_stop_is_stopped_with_completed_sound(self):
        c = running(TABATA, get_ready=5, rounds=None)
        for i in range(1, 8):
            c.handle("ok", T0 + i)                             # GR, then W/R alternately
        c.sounds.clear()
        c.handle("back", T0 + 8)
        c.handle("back", T0 + 8.5)
        self.assertEqual(c.screen, RECAP)
        self.assertTrue(c.workout.stopped)
        self.assertEqual(c.sounds, [app.SOUND_COMPLETED])
        self.assertEqual(stats(c.workout), (4.5, 3, 3))        # W4 cut by stop: no round
        self.assertIn("STOPPED", _texts(app.render_recap(c.workout, "total")))


class StopPromptSkipTest(unittest.TestCase):
    def test_ok_while_stop_is_up_answers_no_then_skips(self):
        c = running(TABATA, get_ready=0, work=20, rest=10, rounds=3)
        c.handle("back", T0 + 5)
        self.assertIsNotNone(c.stop_until)
        c.handle("ok", T0 + 6)
        self.assertIsNone(c.stop_until)
        self.assertEqual((c.screen, c.workout.phase), (RUN, REST))
        self.assertEqual(stats(c.workout), (6, 0, 1))
        c.handle("back", T0 + 6.5)                             # a new prompt, not a stop
        self.assertEqual((c.screen, c.stop_until), (RUN, T0 + 6.5 + app.STOP_CONFIRM))
        self.assertFalse(c.workout.stopped)

    def test_ok_while_stop_is_up_and_paused_answers_no_and_skips_nothing(self):
        c = running(TABATA, get_ready=0)
        c.handle("start", T0 + 5)                              # paused
        c.handle("back", T0 + 6)
        c.handle("ok", T0 + 7)
        self.assertIsNone(c.stop_until)
        self.assertEqual((c.workout.phase, c.workout.paused, stats(c.workout)),
                         (WORK, True, (0, 0, 0)))
        c.handle("start", T0 + 9)                              # resume, then skip works
        c.handle("ok", T0 + 10)
        self.assertEqual((c.workout.phase, stats(c.workout)), (REST, (6, 0, 1)))

    def test_ok_on_the_last_work_while_stop_is_up_is_done_not_stopped(self):
        c = running(TABATA, get_ready=0, rounds=1)
        c.handle("back", T0 + 5)
        c.sounds.clear()
        c.handle("ok", T0 + 6)
        self.assertEqual(c.screen, RECAP)
        self.assertFalse(c.workout.stopped)
        self.assertEqual(c.sounds, [app.SOUND_COMPLETED])
        self.assertIn("DONE", _texts(app.render_recap(c.workout, "work")))
        c.handle("back", T0 + 6.5)                             # prompt was answered: to TYPE
        self.assertEqual((c.screen, c.field), (MENU, "type"))


class SkipSoundsTest(unittest.TestCase):
    def test_skip_into_a_short_fixed_phase_finishes_then_ticks(self):
        c = running(TABATA, get_ready=0, work=20, rest=3, rounds=2)
        c.update(T0 + 5)
        c.sounds.clear()
        c.handle("ok", T0 + 5)                                 # into a 3 s REST
        self.assertEqual(c.sounds, [app.SOUND_FINISH])         # not its first tick
        c.sounds.clear()
        heard = []
        for i in range(1, 31):
            c.update(T0 + 5 + i / 10)
            heard += [(i / 10, s) for s in c.sounds]
            c.sounds.clear()
        self.assertEqual(heard, [(1.0, app.SOUND_TICK), (2.0, app.SOUND_TICK),
                                 (3.0, app.SOUND_FINISH)])

    def test_stop_right_after_skipping_get_ready_is_silent_and_no_round(self):
        c = running(TABATA, get_ready=5)
        c.handle("ok", T0 + 1)
        c.sounds.clear()
        c.handle("back", T0 + 2)
        c.handle("back", T0 + 2)
        self.assertEqual((c.screen, c.sounds, stats(c.workout)), (RECAP, [], (1, 0, 0)))


class SoundTest(unittest.TestCase):
    def started(self, kind=TABATA, get_ready=3, sound=True, **values):
        c = ctrl(last_type=kind, get_ready=get_ready, sound=sound)
        c.cfg["types"][kind].update({"work": 5, "rest": 4, "rounds": 2, **values})
        press(c, *to_summary(kind), "start")
        self.assertEqual(c.screen, RUN)
        return c

    def heard(self, c, start, end, step=0.1):
        """(second, sound) for every sound due between start and end."""
        out = []
        for i in range(int(round((end - start) / step)) + 1):
            now = start + i * step
            c.update(now)
            out += [(round(now - T0, 1), s) for s in c.sounds]
            c.sounds.clear()
        return out

    def test_a_tabata_ticks_finishes_and_completes(self):
        c = self.started()
        tick, finish = app.SOUND_TICK, app.SOUND_FINISH
        self.assertEqual(c.sounds, [tick])                     # get ready 3, right away
        c.sounds.clear()
        self.assertEqual(self.heard(c, T0, T0 + 20), [
            (1.0, tick), (2.0, tick),                          # 2, 1
            (3.0, finish),                                     # WORK 1: 5 4 3 2 1
            (5.0, tick), (6.0, tick), (7.0, tick),
            (8.0, finish),                                     # REST: 4 3 2 1
            (9.0, tick), (10.0, tick), (11.0, tick),
            (12.0, finish),                                    # WORK 2
            (14.0, tick), (15.0, tick), (16.0, tick),
            (17.0, app.SOUND_COMPLETED)])                      # done after the last work
        self.assertEqual(c.screen, RECAP)

    def test_starting_is_silent_with_a_longer_or_no_get_ready(self):
        for get_ready in (0, 5):
            with self.subTest(get_ready=get_ready):
                c = self.started(get_ready=get_ready, work=20)
                self.assertEqual(c.sounds, [])
                ticks = self.heard(c, T0, T0 + 2.05)
                self.assertEqual(ticks, [(2.0, app.SOUND_TICK)] if get_ready else [])

    def test_ok_on_an_open_phase_finishes_it(self):
        c = self.started(FIX_REST, get_ready=0, rest=10)       # open work, then rest
        self.assertEqual(self.heard(c, T0, T0 + 30), [])       # counting up: no ticks
        press(c, "ok", at=T0 + 30.05)
        self.assertEqual(c.sounds, [app.SOUND_FINISH])

    def test_ok_ending_the_last_open_phase_completes(self):
        c = self.started(FIX_REST, get_ready=0, rounds=1)
        press(c, "ok", at=T0 + 3)
        self.assertEqual((c.screen, c.sounds), (RECAP, [app.SOUND_COMPLETED]))

    def skip(self, c, at):
        """The sounds of an OK pressed at `at`, apart from those already due."""
        c.update(at)
        c.sounds.clear()
        press(c, "ok", at=at)
        return c.sounds

    def test_skipping_is_ignored_while_paused(self):
        c = self.started(get_ready=0)                          # WORK 5 s
        press(c, "start", at=T0 + 1)
        self.assertEqual(self.skip(c, T0 + 2), [])
        self.assertEqual((c.workout.phase, c.workout.paused), (WORK, True))

    def test_nothing_ticks_while_paused_and_resuming_is_silent(self):
        c = self.started(get_ready=0)                          # WORK 5 s
        press(c, "start", at=T0 + 2.5)                         # paused showing 3
        c.sounds.clear()
        self.assertEqual(self.heard(c, T0 + 2.5, T0 + 10), [])
        press(c, "start", at=T0 + 10)
        self.assertEqual(c.sounds, [])
        self.assertEqual(self.heard(c, T0 + 10, T0 + 12),     # 2.5 s left: 2, 1
                         [(10.5, app.SOUND_TICK), (11.5, app.SOUND_TICK)])

    def test_stopping_early_is_silent(self):
        c = self.started(get_ready=0)
        press(c, "back", "back", at=T0 + 1)
        self.assertEqual((c.screen, c.sounds), (RECAP, []))

    def test_stopping_an_unlimited_workout_completes_it(self):
        c = self.started(get_ready=0, rounds=None)
        self.heard(c, T0, T0 + 40)                             # a few rounds in
        press(c, "back", "back", at=T0 + 40)
        self.assertEqual((c.screen, c.sounds), (RECAP, [app.SOUND_COMPLETED]))

    def test_stopping_an_unlimited_workout_in_get_ready_is_silent(self):
        c = self.started(get_ready=10, rounds=None)
        press(c, "back", "back", at=T0 + 1)
        self.assertEqual((c.screen, c.sounds), (RECAP, []))

    def test_sound_off_is_silent(self):
        c = self.started(sound=False)
        self.assertEqual(self.heard(c, T0, T0 + 20), [])
        self.assertEqual(c.screen, RECAP)

    def test_a_late_update_gives_one_sound(self):
        c = self.started(get_ready=0)
        c.update(T0 + 6.5)                                     # WORK and part of REST missed
        self.assertEqual(c.sounds, [app.SOUND_FINISH])

    def test_turning_sound_on_plays_a_tick(self):
        c = ctrl(sound=False)
        press(c, -1, "ok", "ok", 1)                            # SETTINGS -> SOUND, turn
        self.assertEqual((c.field, c.cfg["sound"], c.sounds), ("sound", True, [app.SOUND_TICK]))
        press(c, 1)
        self.assertEqual((c.cfg["sound"], c.sounds), (False, [app.SOUND_TICK]))


class RecapPagingTest(unittest.TestCase):
    def finished(self):
        # Tabata 20/10 x1 without get-ready: ends at exactly T0 + 20.
        c = ctrl(get_ready=0)
        c.cfg["types"][TABATA]["rounds"] = 1
        press(c, *to_summary(), "start")
        c.update(T0 + 20.5)
        self.assertEqual(c.screen, RECAP)
        return c

    def test_pages_cycle_every_three_seconds_from_the_end(self):
        c = self.finished()
        pages = [c.recap_page(T0 + 20 + t) for t in (0, 2.9, 3, 6, 9, 12, 3 * 103)]
        self.assertEqual(pages, ["work", "work", "rest", "rounds", "total", "work", "total"])

    def test_cycle_counts_from_the_end_even_if_noticed_late(self):
        c = ctrl(get_ready=0)
        c.cfg["types"][TABATA]["rounds"] = 1
        press(c, *to_summary(), "start")
        c.update(T0 + 27)                           # ended 7 s ago
        self.assertEqual(c.recap_page(T0 + 27), "rounds")

    def test_ok_and_wheel_step_from_the_page_on_screen_and_stop_cycling(self):
        c = self.finished()
        press(c, "ok", at=T0 + 24)                  # showing "rest" -> "rounds"
        self.assertEqual(c.recap_page(T0 + 24), "rounds")
        self.assertEqual(c.recap_page(T0 + 60), "rounds")
        press(c, -1, at=T0 + 61)
        self.assertEqual(c.recap_page(T0 + 61), "rest")
        press(c, 3, at=T0 + 62)                     # wraps around
        self.assertEqual(c.recap_page(T0 + 62), "work")

    def test_wheel_in_the_recap_changes_no_settings(self):
        c = self.finished()
        before = copy.deepcopy(c.cfg)
        press(c, 5, at=T0 + 21)
        self.assertEqual(c.cfg, before)

    def test_a_new_recap_cycles_again(self):
        c = self.finished()
        press(c, "ok", at=T0 + 21)
        press(c, "start", at=T0 + 22)
        c.update(T0 + 42.5)
        self.assertEqual(c.screen, RECAP)
        self.assertEqual(c.recap_page(T0 + 45), "rest")


class SavingTest(unittest.TestCase):
    def test_saved_on_the_next_button_not_on_every_detent(self):
        c = press(ctrl(), "ok", 1, 1, 1)
        self.assertTrue(c.unsaved())
        self.assertFalse(c.save_due)
        press(c, "ok")
        self.assertTrue(c.save_due)
        c.saved()
        self.assertFalse(c.unsaved() or c.save_due)

    def test_choosing_a_type_is_saved(self):
        c = press(ctrl(), 1, "ok")
        self.assertTrue(c.save_due)
        self.assertEqual(c.cfg["last_type"], FIX_REST)

    def test_nothing_changed_nothing_saved(self):
        c = press(ctrl(), "ok", "ok", "back", "back")
        self.assertFalse(c.save_due)


class RenderDispatchTest(unittest.TestCase):
    def test_every_screen_renders_all_slots(self):
        c = ctrl()
        screens = []
        for event in to_summary() + ["start", "back", "back"]:
            screens.append(c.screen)
            self.assertEqual([e["id"] for e in app.render(c, T0)], list(app.SLOTS))
            press(c, event)
        self.assertEqual(screens[-1], RUN)
        self.assertEqual(c.screen, RECAP)
        self.assertEqual([e["id"] for e in app.render(c, T0)], list(app.SLOTS))
        self.assertEqual(set(screens), {MENU, SUMMARY, RUN})


if __name__ == "__main__":
    unittest.main()
