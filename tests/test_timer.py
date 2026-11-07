"""Timer state machine (Workout): all three types, pause/resume, early stop,
stats, skips in every type and phase (SPEC 2, 3, 5.1, 5.3, 5.4 and 7), and
the late-skip grace."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import tearDownModule  # noqa: E402,F401  (first: guards the real settings)
from support import T0, stats  # noqa: E402
import app  # noqa: E402
from app import (DONE, FIX_REST, FIX_WORK, GET_READY, OPEN_CAP, REST,  # noqa: E402
                 TABATA, TYPES, WORK, Workout)


class TabataTest(unittest.TestCase):
    def setUp(self):
        self.w = Workout(TABATA, work=20, rest=10, rounds=3, get_ready=5)

    def test_runs_start_to_finish_without_trailing_rest(self):
        self.assertEqual(self.w.start(T0), [GET_READY])
        self.assertEqual(self.w.update(T0 + 4.9), [])
        self.assertEqual(self.w.update(T0 + 5), [WORK])
        self.assertEqual((self.w.phase, self.w.round), (WORK, 1))
        self.assertEqual(self.w.update(T0 + 25), [REST])
        self.assertEqual(self.w.update(T0 + 35), [WORK])
        self.assertEqual(self.w.round, 2)
        self.assertEqual(self.w.update(T0 + 55), [REST])
        self.assertEqual(self.w.update(T0 + 65), [WORK])
        self.assertEqual(self.w.update(T0 + 85), [DONE])     # no third REST
        s = self.w.stats
        self.assertEqual((s.work_seconds, s.rest_seconds, s.rounds_completed),
                         (60, 20, 3))
        self.assertEqual(s.total_seconds, 80)                # get-ready excluded
        self.assertFalse(self.w.stopped)

    def test_late_update_catches_up_on_exact_boundaries(self):
        # One update long after the start, e.g. after a hung draw request:
        # every boundary is crossed at its exact time, so nothing drifts.
        self.w.start(T0)
        self.assertEqual(self.w.update(T0 + 40), [WORK, REST, WORK])
        self.assertEqual(self.w.round, 2)
        self.assertEqual(self.w.elapsed(T0 + 40), 5)         # round 2 began at +35
        self.assertEqual(self.w.update(T0 + 200), [REST, WORK, DONE])
        self.assertEqual(self.w.stats.total_seconds, 80)

    def test_countdown_display(self):
        self.w.start(T0)
        self.assertEqual(self.w.display_seconds(T0), 5)
        self.assertEqual(self.w.display_seconds(T0 + 4.01), 1)
        self.w.update(T0 + 5)
        self.assertEqual(self.w.display_seconds(T0 + 5), 20)
        self.assertEqual(self.w.display_seconds(T0 + 5.5), 20)
        self.assertEqual(self.w.display_seconds(T0 + 6), 19)
        self.assertEqual(self.w.display_seconds(T0 + 24.99), 1)

    def test_skipping_get_ready_starts_work_at_once(self):
        self.w.start(T0)
        self.assertEqual(self.w.advance(T0 + 2), [WORK])
        self.assertEqual((self.w.round, self.w.stats.total_seconds), (1, 0))
        self.assertEqual(self.w.update(T0 + 21.9), [])
        self.assertEqual(self.w.update(T0 + 22), [REST])     # a full 20 s WORK

    def test_skipping_work_completes_its_round(self):
        self.w.start(T0)
        self.w.update(T0 + 5)
        self.assertEqual(self.w.advance(T0 + 12), [REST])    # 7 s of a 20 s WORK
        s = self.w.stats
        self.assertEqual((s.work_seconds, s.rest_seconds, s.rounds_completed), (7, 0, 1))
        self.assertEqual(self.w.update(T0 + 22), [WORK])     # a full 10 s REST
        self.assertEqual(self.w.round, 2)

    def test_skipping_rest_starts_the_next_round(self):
        self.w.start(T0)
        self.w.update(T0 + 25)                               # REST 1
        self.assertEqual(self.w.advance(T0 + 28), [WORK])
        s = self.w.stats
        self.assertEqual((self.w.round, s.work_seconds, s.rest_seconds, s.rounds_completed),
                         (2, 20, 3, 1))

    def test_skipping_the_last_work_ends_the_workout(self):
        self.w.start(T0)
        self.w.update(T0 + 65)                               # WORK 3 of 3
        self.assertEqual(self.w.advance(T0 + 70), [DONE])    # no trailing rest
        self.assertFalse(self.w.stopped)
        s = self.w.stats
        self.assertEqual((s.work_seconds, s.rest_seconds, s.rounds_completed), (45, 20, 3))

    def test_no_get_ready(self):
        w = Workout(TABATA, work=20, rest=10, rounds=1, get_ready=0)
        self.assertEqual(w.start(T0), [WORK])
        self.assertEqual(w.update(T0 + 20), [DONE])
        self.assertEqual(w.stats.rounds_completed, 1)


class FixedRestTest(unittest.TestCase):
    """WORK is open (counts up, ends on OK), REST is fixed."""

    def setUp(self):
        self.w = Workout(FIX_REST, rest=30, rounds=2, get_ready=0)

    def test_open_work_waits_for_ok(self):
        self.w.start(T0)
        self.assertEqual(self.w.update(T0 + 500), [])        # never ends by itself
        self.assertEqual(self.w.display_seconds(T0 + 42.7), 42)
        self.assertEqual(self.w.advance(T0 + 45), [REST])
        self.assertEqual(self.w.update(T0 + 75), [WORK])
        self.assertEqual(self.w.advance(T0 + 135), [DONE])   # final WORK: no rest
        s = self.w.stats
        self.assertEqual((s.work_seconds, s.rest_seconds, s.rounds_completed),
                         (105, 30, 2))

    def test_open_phase_display_caps_at_99_59(self):
        self.w.start(T0)
        self.assertEqual(self.w.display_seconds(T0 + 2 * 3600), OPEN_CAP)
        self.w.advance(T0 + 2 * 3600)
        self.assertEqual(self.w.stats.work_seconds, 2 * 3600)  # stats keep real time


class FixedWorkTest(unittest.TestCase):
    """WORK is fixed, REST is open (counts up, ends on OK)."""

    def test_open_rest_waits_for_ok(self):
        w = Workout(FIX_WORK, work=40, rounds=2, get_ready=3)
        w.start(T0)
        self.assertEqual(w.update(T0 + 43), [WORK, REST])
        self.assertFalse(w.is_fixed())
        self.assertEqual(w.update(T0 + 300), [])
        self.assertEqual(w.advance(T0 + 103), [WORK])         # rested 60 s
        self.assertEqual(w.update(T0 + 143), [DONE])
        s = w.stats
        self.assertEqual((s.work_seconds, s.rest_seconds, s.rounds_completed),
                         (80, 60, 2))


class PauseTest(unittest.TestCase):
    def test_pause_freezes_phase_and_is_excluded_from_stats(self):
        w = Workout(TABATA, work=20, rest=10, rounds=1, get_ready=0)
        w.start(T0)
        w.toggle_pause(T0 + 8)
        self.assertTrue(w.paused)
        self.assertEqual(w.update(T0 + 100), [])              # frozen
        self.assertEqual(w.display_seconds(T0 + 100), 12)
        w.toggle_pause(T0 + 100)                               # 92 s paused
        self.assertFalse(w.paused)
        self.assertEqual(w.display_seconds(T0 + 100), 12)
        self.assertEqual(w.update(T0 + 111.9), [])
        self.assertEqual(w.update(T0 + 112), [DONE])
        self.assertEqual(w.stats.work_seconds, 20)
        self.assertEqual(w.stats.total_seconds, 20)

    def test_pause_during_get_ready(self):
        w = Workout(TABATA, rounds=1, get_ready=5)
        w.start(T0)
        w.toggle_pause(T0 + 2)
        w.toggle_pause(T0 + 10)
        self.assertEqual(w.update(T0 + 12.9), [])
        self.assertEqual(w.update(T0 + 13), [WORK])

    def test_pause_in_open_phase_and_ok_ignored_while_paused(self):
        w = Workout(FIX_REST, rest=10, rounds=1, get_ready=0)
        w.start(T0)
        w.toggle_pause(T0 + 30)
        self.assertEqual(w.advance(T0 + 40), [])               # OK while paused
        self.assertEqual(w.display_seconds(T0 + 60), 30)
        w.toggle_pause(T0 + 60)
        self.assertEqual(w.advance(T0 + 65), [DONE])
        self.assertEqual(w.stats.work_seconds, 35)

    def test_ok_ignored_while_paused_in_a_fixed_phase(self):
        w = Workout(TABATA, work=20, rest=10, rounds=2, get_ready=0)
        w.start(T0)
        w.toggle_pause(T0 + 8)
        self.assertEqual(w.advance(T0 + 15), [])
        self.assertEqual((w.phase, w.display_seconds(T0 + 15)), (WORK, 12))
        w.toggle_pause(T0 + 15)
        self.assertEqual(w.advance(T0 + 16), [REST])
        self.assertEqual(w.stats.work_seconds, 9)

    def test_pause_that_crosses_a_boundary_ends_the_phase_first(self):
        # START pressed late (update not called since the phase ran out):
        # the phase ends at its boundary and the pause lands in the next one.
        w = Workout(TABATA, work=20, rest=10, rounds=2, get_ready=0)
        w.start(T0)
        self.assertEqual(w.toggle_pause(T0 + 23), [REST])
        self.assertEqual(w.display_seconds(T0 + 50), 7)


class EarlyStopTest(unittest.TestCase):
    def test_stop_mid_work_counts_time_but_not_the_round(self):
        w = Workout(TABATA, work=20, rest=10, rounds=8, get_ready=0)
        w.start(T0)
        w.update(T0 + 37)                                      # round 2 WORK, 7 s in
        self.assertEqual(w.stop(T0 + 37), [DONE])
        self.assertTrue(w.stopped)
        s = w.stats
        self.assertEqual((s.work_seconds, s.rest_seconds, s.rounds_completed),
                         (27, 10, 1))
        self.assertEqual(s.total_seconds, 37)

    def test_stop_mid_rest_keeps_that_round(self):
        w = Workout(TABATA, work=20, rest=10, rounds=8, get_ready=0)
        w.start(T0)
        w.stop(T0 + 24)
        s = w.stats
        self.assertEqual((s.work_seconds, s.rest_seconds, s.rounds_completed),
                         (20, 4, 1))

    def test_stop_while_paused_counts_only_unpaused_time(self):
        w = Workout(FIX_REST, rest=10, rounds=3, get_ready=0)
        w.start(T0)
        w.toggle_pause(T0 + 15)
        w.stop(T0 + 90)
        self.assertFalse(w.paused)
        self.assertEqual(w.stats.work_seconds, 15)
        self.assertEqual(w.stats.rounds_completed, 0)

    def test_stop_during_get_ready_gives_zero_stats(self):
        w = Workout(TABATA, get_ready=5)
        w.start(T0)
        w.stop(T0 + 3)
        s = w.stats
        self.assertEqual((s.work_seconds, s.rest_seconds, s.rounds_completed,
                          s.total_seconds), (0, 0, 0, 0))
        self.assertTrue(w.stopped)

    def test_stop_after_finish_is_a_no_op(self):
        w = Workout(TABATA, work=20, rest=10, rounds=1, get_ready=0)
        w.start(T0)
        self.assertEqual(w.stop(T0 + 30), [DONE])              # finished at +20
        self.assertFalse(w.stopped)
        self.assertEqual(w.stats.work_seconds, 20)


class UnlimitedTest(unittest.TestCase):
    def test_runs_until_stopped(self):
        w = Workout(TABATA, work=20, rest=10, rounds=None, get_ready=0)
        w.start(T0)
        w.update(T0 + 30 * 150)                               # 150 rounds in
        self.assertEqual((w.phase, w.round), (WORK, 151))
        self.assertFalse(w.is_last_round())
        w.stop(T0 + 30 * 150 + 5)
        self.assertEqual(w.stats.rounds_completed, 150)
        self.assertEqual(w.stats.work_seconds, 150 * 20 + 5)


class RestartTest(unittest.TestCase):
    def test_start_again_resets_everything(self):
        w = Workout(TABATA, work=20, rest=10, rounds=2, get_ready=0)
        w.start(T0)
        w.stop(T0 + 25)
        self.assertEqual(w.start(T0 + 100), [WORK])
        self.assertEqual((w.round, w.stopped, w.stats.total_seconds), (1, False, 0))


class ValidationTest(unittest.TestCase):
    def test_unknown_type(self):
        with self.assertRaises(ValueError):
            Workout("hiit")

    def test_zero_durations(self):
        # A 0 s phase would make update() loop forever.
        for kw in ({"work": 0}, {"rest": 0}, {"get_ready": -1}):
            with self.subTest(**kw), self.assertRaises(ValueError):
                Workout(TABATA, **kw)


# --- skips -------------------------------------------------------------------

class SkipEveryPhaseTest(unittest.TestCase):
    """OK ends the current phase at once, in every type and every phase."""

    def test_get_ready_is_skipped_in_every_type(self):
        for kind in TYPES:
            with self.subTest(kind):
                w = Workout(kind, work=20, rest=10, rounds=3, get_ready=15)
                w.start(T0)
                self.assertEqual(w.advance(T0 + 4.25), [WORK])
                self.assertEqual((w.phase, w.round, w.phase_start), (WORK, 1, T0 + 4.25))
                self.assertEqual(stats(w), (0, 0, 0))          # get-ready never counts

    def test_work_is_skipped_in_every_type(self):
        for kind in TYPES:
            with self.subTest(kind):
                w = Workout(kind, work=20, rest=10, rounds=3, get_ready=0)
                w.start(T0)
                self.assertEqual(w.advance(T0 + 7.25), [REST])
                self.assertEqual((w.phase, w.round, w.phase_start), (REST, 1, T0 + 7.25))
                self.assertEqual(stats(w), (7.25, 0, 1))       # an early WORK completes its round

    def test_rest_is_skipped_in_every_type(self):
        for kind in TYPES:
            with self.subTest(kind):
                w = Workout(kind, work=20, rest=10, rounds=3, get_ready=0)
                w.start(T0)
                w.advance(T0 + 5)                              # WORK 1 ended (any type)
                self.assertEqual(w.advance(T0 + 8.5), [WORK])
                self.assertEqual((w.phase, w.round, w.phase_start), (WORK, 2, T0 + 8.5))
                self.assertEqual(stats(w), (5, 3.5, 1))

    def test_a_fixed_phase_after_a_skip_lasts_its_full_time(self):
        # No drift: the next phase starts at the skip, not at the old boundary.
        w = Workout(TABATA, work=20, rest=10, rounds=3, get_ready=5)
        w.start(T0)
        w.advance(T0 + 1)                                      # WORK from T0+1
        self.assertEqual(w.update(T0 + 20.99), [])
        self.assertEqual(w.update(T0 + 21), [REST])            # 20 s later
        w.advance(T0 + 22)                                     # WORK 2 from T0+22
        self.assertEqual(w.display_seconds(T0 + 22), 20)
        self.assertEqual(w.update(T0 + 42), [REST])
        self.assertEqual(stats(w), (40, 1, 2))

    def test_skipping_the_last_work_ends_the_workout_in_every_type(self):
        for kind in TYPES:
            with self.subTest(kind):
                w = Workout(kind, work=20, rest=10, rounds=2, get_ready=5)
                w.start(T0)
                self.assertEqual(w.advance(T0 + 1), [WORK])
                self.assertEqual(w.advance(T0 + 2), [REST])
                self.assertEqual(w.advance(T0 + 3), [WORK])
                self.assertEqual(w.advance(T0 + 4.5), [DONE])  # no trailing rest
                self.assertFalse(w.stopped)
                self.assertFalse(w.running)
                self.assertEqual(stats(w), (2.5, 1, 2))
                self.assertEqual(w.advance(T0 + 5), [])       # nothing left to skip
                self.assertEqual(stats(w), (2.5, 1, 2))

    def test_one_round_tabata_skipped_through(self):
        w = Workout(TABATA, work=20, rest=10, rounds=1, get_ready=5)
        w.start(T0)
        self.assertEqual(w.advance(T0 + 2), [WORK])
        self.assertEqual(w.advance(T0 + 3), [DONE])
        self.assertEqual((stats(w), w.stats.total_seconds, w.stopped), ((1, 0, 1), 1, False))

    def test_minimum_durations(self):
        # 1 s phases, skipped at 0.5 s: nothing runs past or double counts.
        w = Workout(TABATA, work=1, rest=1, rounds=2, get_ready=1)
        w.start(T0)
        self.assertEqual(w.advance(T0 + 0.5), [WORK])
        self.assertEqual(w.advance(T0 + 1.0), [REST])
        self.assertEqual(w.update(T0 + 1.99), [])
        self.assertEqual(w.update(T0 + 2.0), [WORK])           # REST ran its 1 s
        self.assertEqual(w.advance(T0 + 2.5), [DONE])
        self.assertEqual(stats(w), (1.0, 1.0, 2))


class SkipAndPauseTest(unittest.TestCase):
    def test_ignored_while_paused_in_every_type_and_phase(self):
        for kind in TYPES:
            for skips_first, phase in ((0, GET_READY), (1, WORK), (2, REST)):
                with self.subTest(kind=kind, phase=phase):
                    w = Workout(kind, work=20, rest=10, rounds=3, get_ready=5)
                    w.start(T0)
                    for i in range(skips_first):
                        w.advance(T0 + 1 + i)
                    t = T0 + 3.5
                    w.toggle_pause(t)
                    before = (w.phase, w.round, w.phase_start, w.paused_at, stats(w))
                    self.assertEqual(w.advance(t + 30), [])
                    self.assertEqual(w.advance(t + 30), [])
                    self.assertEqual((w.phase, w.round, w.phase_start, w.paused_at, stats(w)),
                                     before)

    def test_skip_after_resume_counts_exactly_the_unpaused_time(self):
        w = Workout(TABATA, work=20, rest=10, rounds=3, get_ready=0)
        w.start(T0)
        w.toggle_pause(T0 + 2)                                 # 2 s in
        w.advance(T0 + 50)                                     # ignored
        w.toggle_pause(T0 + 60)
        w.toggle_pause(T0 + 63)                                # 3 more s in
        w.toggle_pause(T0 + 100)
        self.assertEqual(w.advance(T0 + 101.5), [REST])        # 1.5 more s
        self.assertEqual(stats(w), (6.5, 0, 1))
        w.toggle_pause(T0 + 103)                               # REST: 1.5 s in
        w.toggle_pause(T0 + 200)
        self.assertEqual(w.advance(T0 + 202), [WORK])          # 2 more s
        self.assertEqual(stats(w), (6.5, 3.5, 1))
        self.assertEqual(w.stats.total_seconds, 10)

    def test_paused_in_last_work_then_resumed_and_skipped_is_done(self):
        w = Workout(TABATA, work=20, rest=10, rounds=1, get_ready=0)
        w.start(T0)
        w.toggle_pause(T0 + 4)
        self.assertEqual(w.advance(T0 + 10), [])
        w.toggle_pause(T0 + 10)
        self.assertEqual(w.advance(T0 + 11), [DONE])
        self.assertEqual((stats(w), w.stopped), ((5, 0, 1), False))


class SkipAtBoundaryTest(unittest.TestCase):
    """A skip at exactly a fixed phase's end (now == end): the phase has
    already ended by itself, and the one that just began is in its skip
    grace, so the skip changes nothing more."""

    def test_skip_exactly_when_work_runs_out(self):
        w = Workout(TABATA, work=20, rest=10, rounds=3, get_ready=0)
        w.start(T0)
        self.assertEqual(w.advance(T0 + 20), [REST])
        self.assertEqual((w.phase, w.round, w.phase_start), (REST, 1, T0 + 20))
        self.assertEqual(stats(w), (20, 0, 1))

    def test_skip_exactly_when_the_last_work_runs_out(self):
        w = Workout(TABATA, work=20, rest=10, rounds=1, get_ready=5)
        w.start(T0)
        self.assertEqual(w.advance(T0 + 25), [WORK, DONE])
        self.assertEqual((stats(w), w.stopped), ((20, 0, 1), False))
        self.assertEqual(w.advance(T0 + 25), [])               # no double counting

    def test_skip_exactly_when_get_ready_runs_out(self):
        w = Workout(FIX_WORK, work=20, rounds=2, get_ready=5)
        w.start(T0)
        self.assertEqual(w.advance(T0 + 5), [WORK])            # no 0 s round
        self.assertEqual((w.phase, w.round, stats(w)), (WORK, 1, (0, 0, 0)))

    def test_late_skip_after_several_missed_boundaries(self):
        # update() not called for a while: the fixed phases run out at their
        # own boundaries first, then the skip ends the current one.
        w = Workout(TABATA, work=20, rest=10, rounds=3, get_ready=5)
        w.start(T0)
        self.assertEqual(w.advance(T0 + 40), [WORK, REST, WORK, REST])
        self.assertEqual((w.round, w.phase_start), (2, T0 + 40))
        self.assertEqual(stats(w), (25, 10, 2))


class RapidSkipsTest(unittest.TestCase):
    def test_several_skips_at_one_instant_skip_one_phase_each(self):
        w = Workout(TABATA, work=20, rest=10, rounds=3, get_ready=5)
        w.start(T0)
        entered = []
        for _ in range(4):
            entered += w.advance(T0 + 2)
        self.assertEqual(entered, [WORK, REST, WORK, REST])
        self.assertEqual((w.round, stats(w)), (2, (0, 0, 2)))


class UnlimitedSkipTest(unittest.TestCase):
    def test_skipping_never_ends_an_unlimited_workout_in_any_type(self):
        for kind in TYPES:
            with self.subTest(kind):
                w = Workout(kind, work=20, rest=10, rounds=None, get_ready=5)
                w.start(T0)
                w.advance(T0 + 1)
                t = T0 + 1
                for _ in range(250):
                    t += 0.5
                    w.advance(t)
                self.assertTrue(w.running)
                self.assertEqual((w.phase, w.round, w.stats.rounds_completed),
                                 (WORK, 126, 125))      # 125 W->R, 125 R->W
                self.assertEqual((w.stats.work_seconds, w.stats.rest_seconds), (62.5, 62.5))
                self.assertEqual(w.stop(t + 1), [DONE])
                self.assertTrue(w.stopped)


class RecapTotalsAfterSkipsTest(unittest.TestCase):
    """TOTAL = WORK + REST, and both equal the wall time from the first WORK
    start to the end minus pauses, whatever mix of skips, pauses and natural
    phase ends happened."""

    def test_random_sessions_in_every_type(self):
        for kind in TYPES:
            for seed in range(150):
                with self.subTest(kind=kind, seed=seed):
                    self._session(kind, seed)

    def _session(self, kind, seed):
        rnd = random.Random(seed)
        w = Workout(kind, work=rnd.choice([1, 3, 20]), rest=rnd.choice([1, 4, 10]),
                    rounds=rnd.choice([1, 2, 5, None]), get_ready=rnd.choice([0, 3, 5]))
        w.start(T0)
        t = T0
        if w.phase == GET_READY:                               # skipped, so WORK 1 starts at t
            t += rnd.choice([0.0, 0.4, 1.0])
            w.advance(t)
        first_work = t
        paused_total, pause_from = 0.0, None
        for _ in range(60):
            if not w.running:
                break
            t += rnd.choice([0.0, 0.1, 0.37, 1.0, 2.5, 6.0])
            action = rnd.choice(["ok", "ok", "start", "wait"])
            if action == "ok":
                w.advance(t)
            elif action == "start":
                was_paused = w.paused
                w.toggle_pause(t)
                if was_paused:
                    paused_total += t - pause_from
                elif w.paused:
                    pause_from = t
            else:
                w.update(t)
        if not w.running:
            end = w.phase_start                                # DONE entered at its end
        else:
            end = pause_from if w.paused else t                # stopped paused: up to the pause
            w.stop(t)
        s = w.stats
        self.assertEqual(s.total_seconds, s.work_seconds + s.rest_seconds)
        self.assertAlmostEqual(s.total_seconds, end - first_work - paused_total, places=6)
        self.assertEqual(app.recap_value(w, "total"),
                         app.fmt_time(s.work_seconds + s.rest_seconds, hours=True))
        if w.rounds is not None:
            self.assertLessEqual(s.rounds_completed, w.rounds)
            self.assertEqual(app.recap_value(w, "rounds"), "%d/%d" % (s.rounds_completed, w.rounds))


# --- the late-skip grace -----------------------------------------------------

# A skip in the first SKIP_GRACE s of a phase that began by itself is ignored.

# Every way a phase runs out by itself, as (type, skips first, s after T0
# that it runs out, the phase that runs out), in a 20/10 x3 workout with a
# 5 s get-ready. Open phases never run out, so FIX_REST skips its WORK first.
RUNS_OUT = [
    (TABATA, (), 5, GET_READY), (FIX_REST, (), 5, GET_READY), (FIX_WORK, (), 5, GET_READY),
    (TABATA, (), 25, WORK), (FIX_WORK, (), 25, WORK),
    (TABATA, (), 35, REST), (FIX_REST, (15,), 25, REST),
]


def workout(kind, skips=()):
    w = Workout(kind, work=20, rest=10, rounds=3, get_ready=5)
    w.start(T0)
    for at in skips:
        w.advance(T0 + at)
    return w


def state(w):
    s = w.stats
    return (w.phase, w.round, w.phase_start, s.work_seconds, s.rest_seconds, s.rounds_completed)


class LateSkipTest(unittest.TestCase):
    def test_a_skip_just_after_a_phase_runs_out_is_ignored(self):
        for kind, skips, end, ran_out in RUNS_OUT:
            for noticed in (True, False):           # False: advance()'s own catch-up ends it
                for late in (0.1, 0.49):
                    with self.subTest(kind=kind, ran_out=ran_out, noticed=noticed, late=late):
                        w, ref = workout(kind, skips), workout(kind, skips)
                        caught_up = ref.update(T0 + end)
                        if noticed:
                            self.assertEqual(w.update(T0 + end), caught_up)
                        entered = w.advance(T0 + end + late)
                        self.assertEqual(entered, [] if noticed else caught_up)
                        self.assertEqual(state(w), state(ref))

    def test_from_half_a_second_on_the_skip_works(self):
        for kind, skips, end, ran_out in RUNS_OUT:
            for noticed in (True, False):
                for late in (0.5, 0.6):
                    with self.subTest(kind=kind, ran_out=ran_out, noticed=noticed, late=late):
                        w, ref = workout(kind, skips), workout(kind, skips)
                        ref.update(T0 + end)
                        if noticed:
                            w.update(T0 + end)
                        w.advance(T0 + end + late)
                        self.assertNotEqual(w.phase, ref.phase)
                        self.assertEqual(w.phase_start, T0 + end + late)
                        self.assertAlmostEqual(w.stats.total_seconds,
                                               ref.stats.total_seconds + late)

    def test_a_phase_begun_by_a_skip_can_be_skipped_at_once(self):
        for kind in app.TYPES:
            with self.subTest(kind):
                w = workout(kind)
                w.update(T0 + 5)                        # WORK 1 began by itself
                self.assertEqual(w.advance(T0 + 5.6), [REST])
                self.assertEqual(w.advance(T0 + 5.7), [WORK])   # 0.1 s later: works
                self.assertEqual(w.advance(T0 + 5.75), [REST])
                self.assertEqual((w.round, w.stats.rounds_completed), (2, 2))

    def test_a_phase_begun_by_starting_can_be_skipped_at_once(self):
        w = workout(TABATA)
        self.assertEqual(w.advance(T0 + 0.1), [WORK])           # get-ready
        w = Workout(TABATA, work=20, rest=10, rounds=3, get_ready=0)
        w.start(T0)
        self.assertEqual(w.advance(T0 + 0.1), [REST])           # the first WORK

    def test_paused_time_doesnt_count_towards_the_grace(self):
        w = workout(TABATA)
        w.update(T0 + 5)                                # WORK 1 began by itself
        w.toggle_pause(T0 + 5.25)
        self.assertEqual(w.advance(T0 + 12), [])        # paused: ignored anyway
        w.toggle_pause(T0 + 20)
        self.assertEqual(w.advance(T0 + 20.125), [])    # 0.375 s into the phase
        self.assertEqual((w.phase, w.stats.rounds_completed), (WORK, 0))
        self.assertEqual(w.advance(T0 + 20.25), [REST])  # 0.5 s into it
        self.assertEqual(w.stats.work_seconds, 0.5)


if __name__ == "__main__":
    unittest.main()
