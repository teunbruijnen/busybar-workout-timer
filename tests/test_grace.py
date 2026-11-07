"""Grace for late presses (SPEC 5.1 Skip and the recap, 5.4, 6 Recap):

1. A skip in the first 0.5 s of a phase that began by itself (pauses
   excluded) is ignored.
2. START and OK on the recap are ignored within RECAP_GRACE (1 s) of the
   end; the wheel and BACK are not, and an ignored press still answers a
   pending STOP?.
3. After a stop confirmed with BACK BACK nothing is pending, so BACK on the
   recap goes to TYPE at once; a workout that ends by itself while STOP? is
   up still swallows a BACK in what is left of those 3 s.

Checked through the Controller in every type, for every way a workout ends
and in both SKIP WITH modes, and through the real main() loop (0.1 s passes,
stub bar and input), so a press that arrives just after a boundary is
handled in the same pass that notices it. The Workout's own late-skip grace
is in test_timer."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import tearDownModule  # noqa: E402,F401  (first: guards the real settings)
from support import T0, run_main, running, stats, to_summary  # noqa: E402
import app  # noqa: E402
from app import (DONE, FIX_REST, FIX_WORK, GET_READY, MENU, RECAP, REST,  # noqa: E402
                 RUN, TABATA, WORK, Controller, Wheel)

MODES = app.SKIP_BUTTONS                      # SKIP WITH: "ok" or "start"
PAUSE_WITH = {"ok": "start", "start": "ok"}


def config(kind, skip_with, work=20, rest=10, rounds=3, get_ready=5, sound=True):
    cfg = app.default_config()
    cfg.update(last_type=kind, get_ready=get_ready, sound=sound, skip_with=skip_with)
    cfg["types"][kind].update(work=work, rest=rest, rounds=rounds)
    return cfg


def started(kind, skip_with, **kw):
    c = Controller(config(kind, skip_with, **kw))
    c.start(T0)
    return c


# --- the skip grace ----------------------------------------------------------

# Every automatic phase change in a 20/10 x3 workout with a 5 s get-ready:
# (type, s after T0 of skips needed first, s after T0 it happens, before, after).
# FIX_REST's WORK is open, so its REST -> WORK needs WORK 1 skipped first;
# FIX_WORK's REST is open, so it never runs out.
BOUNDARIES = [
    (TABATA, (), 5, GET_READY, WORK), (TABATA, (), 25, WORK, REST), (TABATA, (), 35, REST, WORK),
    (FIX_REST, (), 5, GET_READY, WORK), (FIX_REST, (15,), 25, REST, WORK),
    (FIX_WORK, (), 5, GET_READY, WORK), (FIX_WORK, (), 25, WORK, REST),
]


def at_boundary(kind, skip_with, skips, noticed, end):
    """A running controller just before (or, `noticed`, at) the boundary,
    sounds cleared."""
    c = started(kind, skip_with)
    for at in skips:
        c.handle(skip_with, T0 + at)
    c.update(T0 + end - 0.05)
    if noticed:
        c.update(T0 + end)
    c.sounds.clear()
    return c


class BoundaryTest(unittest.TestCase):
    """+0.49 s after an automatic change: ignored; +0.5 and +0.51: skips."""

    def test_just_inside_the_grace_the_skip_is_ignored(self):
        for kind, skips, end, before, after in BOUNDARIES:
            for mode in MODES:
                for noticed in (True, False):
                    with self.subTest(kind=kind, change=(before, after), mode=mode,
                                      noticed=noticed):
                        ref = at_boundary(kind, mode, skips, True, end)
                        c = at_boundary(kind, mode, skips, noticed, end)
                        c.handle(mode, T0 + end + 0.49)
                        w = c.workout
                        self.assertEqual((c.screen, w.phase, w.phase_start), (RUN, after, T0 + end))
                        self.assertEqual(stats(w), stats(ref.workout))      # nothing banked
                        # Only the boundary's own sound, and only if this
                        # press is what noticed the boundary.
                        self.assertEqual(c.sounds, [] if noticed else [app.SOUND_FINISH])

    def test_from_half_a_second_the_skip_works(self):
        for kind, skips, end, before, after in BOUNDARIES:
            for mode in MODES:
                for late in (0.5, 0.51):
                    with self.subTest(kind=kind, change=(before, after), mode=mode, late=late):
                        ref = at_boundary(kind, mode, skips, True, end)
                        c = at_boundary(kind, mode, skips, True, end)
                        c.handle(mode, T0 + end + late)
                        w = c.workout
                        self.assertNotEqual(w.phase, after)
                        self.assertEqual(w.phase_start, T0 + end + late)
                        rw, rr, rn = stats(ref.workout)
                        want = ((rw + late, rr, rn + 1) if after == WORK
                                else (rw, rr + late, rn))
                        for have, expect in zip(stats(w), want):
                            self.assertAlmostEqual(have, expect)
                        self.assertEqual(c.sounds, [app.SOUND_FINISH])

    def test_the_pause_button_is_not_held_back_by_the_grace(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                c = at_boundary(TABATA, mode, (), True, 5)
                c.handle(PAUSE_WITH[mode], T0 + 5.1)
                self.assertTrue(c.workout.paused)


class DoubleSkipTest(unittest.TestCase):
    def test_skip_then_skip_a_tenth_later_skips_two_phases(self):
        for kind, skips, end, before, after in BOUNDARIES:
            for mode in MODES:
                with self.subTest(kind=kind, change=(before, after), mode=mode):
                    c = at_boundary(kind, mode, skips, True, end)
                    w = c.workout
                    c.handle(mode, T0 + end + 2)            # well past the grace
                    first = w.phase
                    self.assertNotEqual(first, after)
                    c.handle(mode, T0 + end + 2.1)          # began by a skip: no grace
                    self.assertNotEqual(w.phase, first)
                    self.assertEqual(w.phase_start, T0 + end + 2.1)

    def test_double_skip_from_the_start(self):
        for kind in app.TYPES:
            for mode in MODES:
                with self.subTest(kind=kind, mode=mode):
                    c = started(kind, mode)
                    c.handle(mode, T0 + 0.1)                # get-ready, begun by start
                    c.handle(mode, T0 + 0.2)                # WORK 1, begun by a skip
                    self.assertEqual((c.workout.phase, c.workout.round), (REST, 1))
                    self.assertAlmostEqual(c.workout.stats.work_seconds, 0.1)
                    self.assertEqual(c.workout.stats.rounds_completed, 1)

    def test_grace_does_not_leak_into_a_repeated_workout(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                c = started(TABATA, mode, rounds=1, get_ready=0)
                c.update(T0 + 20)                           # ended by itself
                c.handle("start", T0 + 21.5)                # repeat, no get-ready
                self.assertEqual((c.screen, c.workout.phase), (RUN, WORK))
                c.handle(mode, T0 + 21.6)                   # WORK begun by start
                self.assertEqual((c.screen, c.workout.phase), (RECAP, DONE))   # its only round


class PauseInGraceTest(unittest.TestCase):
    """The grace counts phase time: paused time doesn't use it up."""

    def test_pause_straight_after_an_automatic_change(self):
        for kind, skips, end, before, after in BOUNDARIES:
            for mode in MODES:
                with self.subTest(kind=kind, change=(before, after), mode=mode):
                    c = at_boundary(kind, mode, skips, True, end)
                    w, pause = c.workout, PAUSE_WITH[mode]
                    c.handle(pause, T0 + end + 0.1)
                    c.handle(mode, T0 + end + 3)            # paused: ignored
                    c.handle(pause, T0 + end + 10)          # 0.1 s into the phase
                    c.handle(mode, T0 + end + 10.3)         # 0.4 s: still in grace
                    self.assertEqual((w.phase, w.phase_start), (after, T0 + end + 9.9))
                    c.handle(mode, T0 + end + 10.4)         # 0.5 s: skips
                    self.assertNotEqual(w.phase, after)


class StopPromptTest(unittest.TestCase):
    def test_an_ignored_skip_still_answers_no(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                c = at_boundary(TABATA, mode, (), False, 25)
                c.handle("back", T0 + 24.98)                # STOP? up
                c.handle(mode, T0 + 25.2)                   # in WORK->REST grace
                self.assertIsNone(c.stop_until)
                self.assertEqual((c.workout.phase, stats(c.workout)), (REST, (20, 0, 1)))
                c.handle("back", T0 + 25.3)                 # a new prompt, not a stop
                self.assertEqual((c.screen, c.workout.stopped), (RUN, False))
                self.assertIsNotNone(c.stop_until)


# --- the recap: START's and OK's grace, paging after it, BACK after a stop ---

# Every way a workout ends: each returns (a controller on the recap, the end time).

def end_tabata(mode, notice=True):
    c = started(TABATA, mode, rounds=1, get_ready=0)
    if notice:
        c.update(T0 + 20)
    return c, T0 + 20


def end_fix_work(mode, notice=True):
    c = started(FIX_WORK, mode, rounds=1, get_ready=0)
    if notice:
        c.update(T0 + 20)
    return c, T0 + 20


def end_fix_rest_skipped(mode, notice=True):
    c = started(FIX_REST, mode, rounds=1, get_ready=0)
    c.handle(mode, T0 + 12)                     # skips the open last WORK
    return c, T0 + 12


def end_stopped_in_work(mode, notice=True):
    c = started(TABATA, mode)
    c.handle("back", T0 + 12)
    c.handle("back", T0 + 14.5)
    return c, T0 + 14.5


def end_stopped_paused(mode, notice=True):
    c = started(FIX_WORK, mode)
    c.handle(PAUSE_WITH[mode], T0 + 8)          # paused in WORK 1
    c.handle("back", T0 + 30)
    c.handle("back", T0 + 31)
    assert c.workout.paused_at is None and c.workout.stopped
    return c, T0 + 31


def end_stopped_get_ready(mode, notice=True):
    c = started(FIX_REST, mode)
    c.handle("back", T0 + 1)
    c.handle("back", T0 + 1.25)
    return c, T0 + 1.25


def end_unlimited_stopped(mode, notice=True):
    c = started(TABATA, mode, rounds=None)
    c.handle("back", T0 + 40)
    c.handle("back", T0 + 40)
    return c, T0 + 40


ENDINGS = {
    "tabata by itself": end_tabata,
    "fixed work by itself": end_fix_work,
    "fixed rest skipped": end_fix_rest_skipped,
    "stopped in work": end_stopped_in_work,
    "stopped while paused": end_stopped_paused,
    "stopped in get-ready": end_stopped_get_ready,
    "unlimited stopped": end_unlimited_stopped,
}


class RecapGraceTest(unittest.TestCase):
    def test_start_is_ignored_for_one_second_after_any_end(self):
        for how, make in ENDINGS.items():
            for mode in MODES:
                for late, restarts in ((0.3, False), (0.5, False), (0.99, False), (1.0, True),
                                       (1.5, True)):
                    with self.subTest(how=how, mode=mode, late=late):
                        c, end = make(mode)
                        self.assertEqual(c.screen, RECAP)
                        done, page = c.workout, c.recap_page(end + late)
                        c.sounds.clear()
                        c.handle("start", end + late)
                        if restarts:
                            self.assertEqual((c.screen, c.workout.phase),
                                             (RUN, GET_READY if c.cfg["get_ready"] else WORK))
                            self.assertIsNot(c.workout, done)
                        else:
                            self.assertEqual((c.screen, c.workout, c.page), (RECAP, done, None))
                            self.assertEqual(c.recap_page(end + late), page)
                            self.assertEqual(done.phase, DONE)
                            self.assertEqual(c.sounds, [])

    def test_ok_is_ignored_for_one_second_too_but_back_works_at_once(self):
        for how, make in ENDINGS.items():
            for mode in MODES:
                with self.subTest(how=how, mode=mode):
                    c, end = make(mode)
                    c.handle("ok", end + 0.1)
                    self.assertEqual((c.screen, c.page), (RECAP, None))
                    c.handle("ok", end + 1.0)
                    self.assertEqual((c.screen, c.page), (RECAP, "rest"))
                    c, end = make(mode)
                    c.handle("back", end + 0.1)
                    self.assertEqual((c.screen, c.field, c.choice), (MENU, "type", c.kind))

    def test_counted_from_the_end_not_from_when_the_recap_appeared(self):
        c = running(skip_with="ok", get_ready=0, rounds=1)
        c.update(T0 + 20.8)                             # noticed late
        c.handle("start", T0 + 21)
        self.assertEqual(c.screen, RUN)


def snapshot(c, now):
    """What the recap shows and keeps, apart from `page`."""
    return (c.screen, c.recap_page(now), c.stop_until, c.workout.phase,
            c.workout.stopped, vars(c.workout.stats).copy(), list(c.sounds),
            app.render(c, now))


class OkGraceBoundaryTest(unittest.TestCase):
    def test_ok_ignored_before_one_second_pages_from_one_second(self):
        lates = ((0.0, False), (0.5, False), (0.99, False), (0.999999, False),
                 (1.0, True), (1.0001, True), (1.5, True))
        for name, make in ENDINGS.items():
            for mode in MODES:
                for notice in (True, False):     # False: handle() notices the end itself
                    for late, pages in lates:
                        with self.subTest(end=name, mode=mode, notice=notice, late=late):
                            c, end = make(mode, notice)
                            done = c.workout
                            c.sounds.clear()
                            c.handle("ok", end + late)
                            self.assertEqual(c.screen, RECAP)
                            self.assertIs(c.workout, done)
                            if notice:
                                self.assertEqual(c.sounds, [])
                            self.assertEqual(c.page, "rest" if pages else None)
                            self.assertEqual(app.changes_by_itself(c), not pages)

    def test_an_ignored_ok_changes_nothing(self):
        for name, make in ENDINGS.items():
            for mode in MODES:
                with self.subTest(end=name, mode=mode):
                    c, end = make(mode)
                    ref, _ = make(mode)
                    c.sounds.clear(), ref.sounds.clear()
                    for late in (0.0, 0.1, 0.5, 0.99):
                        c.handle("ok", end + late)
                    for k in range(0, 81):       # 0 .. 20 s, auto-paging intact
                        t = end + k * 0.25
                        self.assertEqual(snapshot(c, t), snapshot(ref, t))
                    self.assertIsNone(c.page)
                    self.assertFalse(c.save_due)

    def test_the_skip_double_press_that_ended_it(self):
        """The case the rule is for: two quick presses of the skip button on
        the last phase; the second lands on the recap."""
        for kind in (TABATA, FIX_REST, FIX_WORK):
            for mode in MODES:
                with self.subTest(kind=kind, mode=mode):
                    c = started(kind, mode, rounds=1, get_ready=0)
                    c.handle(mode, T0 + 5)               # ends the last WORK
                    self.assertEqual((c.screen, c.workout.stopped), (RECAP, False))
                    c.handle(mode, T0 + 5.15)            # the double
                    self.assertEqual((c.screen, c.page), (RECAP, None))
                    self.assertEqual(c.workout.stats.work_seconds, 5)


class PagingAfterGraceTest(unittest.TestCase):
    def test_first_ok_steps_on_from_the_page_on_screen(self):
        # (s after the end, page on screen, page after OK)
        cases = [(1.0, "work", "rest"), (2.99, "work", "rest"), (3.0, "rest", "rounds"),
                 (5.5, "rest", "rounds"), (6.0, "rounds", "total"), (9.0, "total", "work"),
                 (11.99, "total", "work"), (12.0, "work", "rest"), (27.5, "rest", "rounds")]
        for name, make in ENDINGS.items():
            for mode in MODES:
                for late, on_screen, after in cases:
                    with self.subTest(end=name, mode=mode, late=late):
                        c, end = make(mode)
                        c.handle("ok", end + 0.5)                 # ignored first
                        self.assertEqual(c.recap_page(end + late), on_screen)
                        c.handle("ok", end + late)
                        self.assertEqual(c.page, after)
                        self.assertEqual(c.recap_page(end + late + 100), after)  # stays

    def test_ok_after_the_grace_keeps_wrapping(self):
        c, end = end_tabata("ok")
        seen = []
        for i in range(6):
            c.handle("ok", end + 1.0 + i * 0.1)
            seen.append(c.page)
        self.assertEqual(seen, ["rest", "rounds", "total", "work", "rest", "rounds"])

    def test_wheel_works_inside_the_grace_but_ok_still_doesnt(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                c, end = end_tabata(mode)
                c.handle(Wheel(1, end + 0.1, False), end + 0.1)
                self.assertEqual(c.page, "rest")
                c.handle("ok", end + 0.2)                     # still within 1 s
                self.assertEqual(c.page, "rest")
                c.handle(Wheel(-1, end + 0.3, False), end + 0.3)
                self.assertEqual(c.page, "work")
                c.handle(Wheel(3, end + 0.4, True), end + 0.4)    # big held burst: ignored
                self.assertEqual(c.page, "work")
                c.handle(Wheel(2, end + 0.5, True), end + 0.5)
                self.assertEqual(c.page, "rounds")
                c.handle("ok", end + 1.0)
                self.assertEqual(c.page, "total")


class BackAfterStopTest(unittest.TestCase):
    STOPS = [  # (type, what happens first, s after T0 of the 1st BACK, gap to the 2nd)
        (TABATA, (), 2, 0.0), (TABATA, (), 12, 2.99), (TABATA, (), 27, 1.0),
        (FIX_REST, (), 12, 0.5), (FIX_REST, ("skip@15",), 20, 2.5),
        (FIX_WORK, (), 12, 0.2), (FIX_WORK, ("skip@25.5",), 30, 2.0),
        (TABATA, ("pause@8",), 20, 1.0), (FIX_REST, ("pause@3",), 10, 2.99),
    ]

    def stopped(self, kind, mode, first, at, gap, releases):
        c = started(kind, mode)
        for f in first:
            what, when = f.split("@")
            c.handle(mode if what == "skip" else PAUSE_WITH[mode], T0 + float(when))
        c.handle("back", T0 + at)
        if releases:
            c.handle(("release", "back"), T0 + at + gap / 2)
        c.handle("back", T0 + at + gap)
        if releases:
            c.handle(("release", "back"), T0 + at + gap)
        self.assertEqual((c.screen, c.workout.stopped, c.stop_until), (RECAP, True, None))
        return c, T0 + at + gap

    def test_back_goes_to_type_at_once(self):
        for kind, first, at, gap in self.STOPS:
            for mode in MODES:
                for releases in (False, True):
                    for late in (0.0, 0.06, 0.5, 0.99, 2.0):
                        with self.subTest(kind=kind, first=first, gap=gap, mode=mode,
                                          releases=releases, late=late):
                            c, end = self.stopped(kind, mode, first, at, gap, releases)
                            c.handle("back", end + late)
                            self.assertEqual((c.screen, c.field, c.choice),
                                             (MENU, "type", kind))

    def test_unlimited_stop_then_back(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                c, end = end_unlimited_stopped(mode)
                self.assertEqual(c.sounds[-1:], [app.SOUND_COMPLETED])
                c.handle("back", end + 0.1)
                self.assertEqual((c.screen, c.field, c.choice), (MENU, "type", TABATA))

    def test_a_stop_prompt_running_out_is_still_not_a_stop(self):
        c = started(TABATA, "ok")
        c.handle("back", T0 + 8)
        c.handle("back", T0 + 11)                 # 3.0 s: a new prompt, not a stop
        self.assertEqual((c.screen, c.workout.stopped, c.stop_until), (RUN, False, T0 + 14))


class EndedWhileStopPromptUpTest(unittest.TestCase):
    """Tabata / Fixed work, last WORK ends at T0 + 20; STOP? raised at
    T0 + 19.5, so it is pending until T0 + 22.5."""

    def ended(self, kind, mode, notice=True):
        c = started(kind, mode, rounds=1, get_ready=0)
        c.handle("back", T0 + 19.5)
        if notice:
            c.update(T0 + 20)
        return c

    def test_back_in_the_rest_of_the_three_seconds_is_swallowed_once(self):
        for kind in (TABATA, FIX_WORK):
            for mode in MODES:
                for notice in (True, False):
                    for late in (0.0, 0.1, 1.0, 2.49):
                        with self.subTest(kind=kind, mode=mode, notice=notice, late=late):
                            c = self.ended(kind, mode, notice)
                            c.handle("back", T0 + 20 + late)
                            self.assertEqual((c.screen, c.stop_until, c.page), (RECAP, None, None))
                            self.assertFalse(c.workout.stopped)
                            c.handle("back", T0 + 20 + late + 0.05)
                            self.assertEqual((c.screen, c.field), (MENU, "type"))

    def test_back_once_the_prompt_ran_out_goes_to_type(self):
        for mode in MODES:
            for late in (2.5, 2.6):
                with self.subTest(mode=mode, late=late):
                    c = self.ended(TABATA, mode)
                    c.handle("back", T0 + 20 + late)
                    self.assertEqual((c.screen, c.field), (MENU, "type"))

    def test_ok_after_the_grace_answers_the_prompt_and_pages(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                c = self.ended(TABATA, mode)
                c.handle("ok", T0 + 21.2)
                self.assertEqual((c.page, c.stop_until), ("rest", None))
                c.handle("back", T0 + 21.4)
                self.assertEqual((c.screen, c.field), (MENU, "type"))

    def test_ignored_ok_or_start_at_the_grace_edge_answers_the_prompt(self):
        for button in MODES:
            for mode in MODES:
                with self.subTest(button=button, mode=mode):
                    c = self.ended(FIX_WORK, mode)
                    c.handle(button, T0 + 20.99)
                    self.assertEqual((c.screen, c.page, c.stop_until), (RECAP, None, None))
                    c.handle("back", T0 + 21.0)
                    self.assertEqual((c.screen, c.field), (MENU, "type"))

    def test_the_wheel_doesnt_answer_the_prompt(self):
        c = self.ended(TABATA, "ok")
        c.handle(Wheel(1, T0 + 20.2, False), T0 + 20.2)
        self.assertEqual((c.page, c.stop_until), ("rest", T0 + 22.5))
        c.handle("back", T0 + 20.4)
        self.assertEqual((c.screen, c.stop_until), (RECAP, None))


# --- the real main() loop ----------------------------------------------------

S = 1.0          # the START that begins the workout, s after T0
# Short phases (work 4, rest 3, get-ready 3) to keep the loop runs short:
# (type, skips first, boundary s after S, phase it begins).
LOOP_BOUNDARIES = [
    (TABATA, (), 3, WORK), (TABATA, (), 7, REST), (TABATA, (), 10, WORK),
    (FIX_REST, (), 3, WORK), (FIX_REST, (4,), 7, WORK),
    (FIX_WORK, (), 3, WORK), (FIX_WORK, (), 7, REST),
]


def loop_events(kind, mode, skips, grid):
    evs = [(0.1 * (i + 1), ok) for i, ok in enumerate(to_summary(kind))]
    evs.append((S, "start"))
    if grid:
        evs.append((S + grid, ("release", "start")))         # shifts the loop's pass grid
    evs += [(S + at, mode) for at in skips]
    return evs


class MainLoopTest(unittest.TestCase):
    """A press arriving 0-0.1 s after a boundary, through main()."""

    def run_case(self, kind, mode, skips, at, late, grid, wake_early):
        cfg = config(kind, mode, work=4, rest=3, rounds=3, get_ready=3)
        evs = loop_events(kind, mode, skips, grid) + [(S + at + late, mode)]
        return run_main(evs, end=S + at + 1.0, cfg=cfg, wake_early=wake_early)

    def test_a_press_just_after_a_boundary_is_ignored(self):
        same_pass = 0
        for kind, skips, at, after in LOOP_BOUNDARIES:
            for mode in MODES:
                for grid in (0, 0.05):
                    for late in (0.0, 0.01, 0.05, 0.1):
                        for wake_early in (True, False):
                            with self.subTest(kind=kind, at=at, mode=mode, grid=grid,
                                              late=late, wake_early=wake_early):
                                run = self.run_case(kind, mode, skips, at, late, grid,
                                                    wake_early)
                                c, plays, passes = run.ctrl, run.plays, run.passes
                                w = c.workout
                                self.assertEqual((c.screen, w.phase), (RUN, after))
                                self.assertAlmostEqual(w.phase_start, T0 + S + at)
                                finishes = [t for t, s in plays
                                            if s == app.SOUND_FINISH and t >= S + at - 1e-6]
                                self.assertEqual(len(finishes), 1, plays)
                                # Was the press handled in the pass that
                                # noticed the boundary?
                                for t, phase, out in passes:
                                    if mode in out and t >= S + at:
                                        same_pass += phase != after
        self.assertGreater(same_pass, 0)

    def test_after_the_grace_the_press_skips(self):
        for kind, skips, at, after in LOOP_BOUNDARIES:
            for mode in MODES:
                with self.subTest(kind=kind, at=at, mode=mode):
                    run = self.run_case(kind, mode, skips, at, 0.6, 0.05, True)
                    c, plays = run.ctrl, run.plays
                    self.assertNotEqual(c.workout.phase, after)
                    self.assertAlmostEqual(c.workout.phase_start, T0 + S + at + 0.6)
                    finishes = [t for t, s in plays if s == app.SOUND_FINISH and t >= S + at - 1e-6]
                    self.assertEqual(len(finishes), 2, plays)

    def test_a_double_start_skip_on_the_last_phase_keeps_the_recap(self):
        cfg = config(TABATA, "start", work=4, rest=3, rounds=1, get_ready=0)
        for gap in (0.1, 0.15, 0.5, 0.9):
            with self.subTest(gap=gap):
                evs = loop_events(TABATA, "start", (), 0)
                evs += [(S + 2, "start"), (S + 2 + gap, "start")]
                c = run_main(evs, end=S + 4, cfg=cfg).ctrl
                self.assertEqual((c.screen, c.workout.stopped), (RECAP, False))
                self.assertAlmostEqual(c.workout.stats.work_seconds, 2)

    def test_a_late_start_after_the_workout_runs_out_keeps_the_recap(self):
        cfg = config(TABATA, "start", work=4, rest=3, rounds=1, get_ready=0)
        for late in (0.0, 0.05, 0.1, 0.5):
            for wake_early in (True, False):
                with self.subTest(late=late, wake_early=wake_early):
                    evs = loop_events(TABATA, "start", (), 0.05) + [(S + 4 + late, "start")]
                    run = run_main(evs, end=S + 6, cfg=cfg, wake_early=wake_early)
                    c, plays = run.ctrl, run.plays
                    self.assertEqual((c.screen, c.workout.stopped), (RECAP, False))
                    self.assertEqual([s for t, s in plays if t >= S + 4 - 1e-6],
                                     [app.SOUND_COMPLETED])


class MainLoopOkGraceTest(unittest.TestCase):
    """Through main(): Tabata 4/3 x1 with a 3 s get-ready ends at S + 7."""

    def test_ok_in_the_pass_that_notices_the_end_is_ignored(self):
        for mode in MODES:
            # wake_early=False handles a press up to TICK late: keep clear of 1.0
            for late, page in ((0.05, None), (0.85, None), (1.05, "rest")):
                for wake_early in (True, False):
                    with self.subTest(mode=mode, late=late, wake_early=wake_early):
                        cfg = config(TABATA, mode, work=4, rest=3, rounds=1, get_ready=3)
                        evs = loop_events(TABATA, mode, (), 0) + [(S + 7 + late, "ok")]
                        run = run_main(evs, end=S + 9, cfg=cfg, wake_early=wake_early)
                        c, plays = run.ctrl, run.plays
                        self.assertEqual((c.screen, c.page), (RECAP, page))
                        self.assertIn(app.SOUND_COMPLETED, [s for _, s in plays])

    def test_back_back_then_back_through_main(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                cfg = config(TABATA, mode, work=4, rest=3, rounds=2, get_ready=3)
                evs = loop_events(TABATA, mode, (), 0) + [
                    (S + 4, "back"), (S + 4.1, ("release", "back")),
                    (S + 4.3, "back"), (S + 4.4, ("release", "back")),
                    (S + 4.6, "back")]
                c = run_main(evs, end=S + 5, cfg=cfg).ctrl
                self.assertEqual((c.screen, c.field, c.choice), (MENU, "type", TABATA))
                self.assertTrue(c.workout.stopped)


if __name__ == "__main__":
    unittest.main()
