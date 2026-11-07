"""DrawSchedule: when the loop draws and what it sends, on a fake clock and
a fake bar; and which screens change by themselves (changes_by_itself)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import tearDownModule  # noqa: E402,F401  (first: guards the real settings)
from support import T0, Hand  # noqa: E402
import app  # noqa: E402
from app import (FIX_WORK, MINUTES, RECAP, RUN, SECONDS, SUMMARY, TABATA,  # noqa: E402
                 TIME_FIELDS, TYPE_FIELDS)


class FakeBar:
    """Records every draw; a draw fails while `failing`, taking `slow` s."""

    def __init__(self):
        self.now = T0
        self.draws = []
        self.failing = False
        self.slow = 0.0
        self.installs = 0
        self.install_result = True

    def draw(self, elements):
        self.draws.append([el["id"] for el in elements])
        self.now += self.slow
        return not self.failing

    def install_sounds(self):
        self.installs += 1
        return self.install_result


class DrawScheduleTest(unittest.TestCase):
    def setUp(self):
        self.bar = FakeBar()
        self.schedule = app.DrawSchedule(self.bar.draw, self.bar.install_sounds,
                                         lambda: self.bar.now)
        cfg = app.default_config()
        self.ready = app.render_menu(cfg, "get_ready", TABATA)       # "5 SEC"
        cfg["get_ready"] = 6
        self.ready6 = app.render_menu(cfg, "get_ready", TABATA)
        self.renders = 0

    def draw(self, t, frame=None, unchanged=False):
        """One pass at T0 + t; the draws it sent, as lists of ids."""
        def build_frame():
            self.renders += 1
            return frame or self.ready
        self.bar.now = T0 + t
        before = len(self.bar.draws)
        self.schedule.draw(T0 + t, build_frame, unchanged=unchanged)
        return self.bar.draws[before:]

    def test_first_draw_is_full_then_only_what_changed(self):
        visible, wipes = self.draw(0)
        self.assertEqual(visible, ["label", "value"])
        self.assertEqual(sorted(visible + wipes), sorted(app.SLOTS))
        self.assertEqual(self.draw(0.1), [])
        self.assertEqual(self.draw(0.2, self.ready6), [["value"]])

    def test_everything_visible_again_every_refresh(self):
        self.draw(0)
        self.assertEqual(self.draw(app.REFRESH - 0.1), [])
        self.assertEqual(self.draw(app.REFRESH), [["label", "value"]])
        self.assertEqual(self.draw(2 * app.REFRESH - 0.1), [])
        self.assertEqual(self.draw(2 * app.REFRESH), [["label", "value"]])

    def test_back_resends_everything_for_a_moment_then_back_to_refresh(self):
        self.draw(0)
        self.schedule.reclaim(T0 + 1)
        visible, wipes = self.draw(1)                    # all of it: the bar
        self.assertEqual(sorted(visible + wipes), sorted(app.SLOTS))   # was cleared
        passes = (1.1, 1.16, 1.3, 1.32, 1.46, 1.48, 1.64, 1.8, 1.96, 2.1, 2.12, 2.2)
        full = [t for t in passes if self.draw(t)]
        # RECLAIM_EVERY s after each one until RECLAIM s after BACK; the one
        # at 2.12 s is past that and sets the next one REFRESH s later.
        self.assertEqual(full, [1.16, 1.32, 1.48, 1.64, 1.8, 1.96, 2.12])
        self.assertEqual(self.draw(2.11 + app.REFRESH), [])
        self.assertEqual(self.draw(2.13 + app.REFRESH), [["label", "value"]])

    def test_a_failed_draw_holds_off_retry_from_after_it_then_draws_in_full(self):
        self.draw(0)
        self.bar.failing, self.bar.slow = True, 0.5      # e.g. a timeout
        self.assertEqual(self.draw(1, self.ready6), [["value"]])
        self.bar.failing, self.bar.slow = False, 0.0
        renders = self.renders
        self.assertEqual(self.draw(1 + app.RETRY), [])           # still held:
        self.assertEqual(self.draw(1.4 + app.RETRY), [])         # 1.5 s + RETRY
        self.assertEqual(self.renders, renders)                  # (nothing built)
        visible, wipes = self.draw(1.5 + app.RETRY, self.ready6)
        self.assertEqual(visible, ["label", "value"])
        self.assertEqual(sorted(visible + wipes), sorted(app.SLOTS))

    def test_sounds_are_copied_once_the_bar_answers(self):
        self.bar.failing = True
        self.draw(0)
        self.assertEqual(self.bar.installs, 0)           # not while draws fail
        self.bar.failing = False
        self.bar.install_result = False                  # the bar went away again
        self.draw(app.RETRY)
        self.assertEqual(self.bar.installs, 1)
        self.draw(app.RETRY + 0.5, unchanged=True)
        self.assertEqual(self.bar.installs, 1)           # at most every RETRY s
        self.bar.install_result = True
        self.draw(2 * app.RETRY, unchanged=True)         # a still screen counts too
        self.assertEqual(self.bar.installs, 2)
        self.draw(3 * app.RETRY)
        self.assertEqual(self.bar.installs, 2)           # done for good

    def test_a_still_frame_is_not_even_built(self):
        self.draw(0)
        renders = self.renders
        self.assertEqual(self.draw(0.1, unchanged=True), [])
        self.assertEqual(self.renders, renders)

    def test_input_or_a_due_refresh_builds_the_frame(self):
        self.draw(0)
        self.assertEqual(self.draw(0.1, self.ready6), [["value"]])
        self.assertEqual(self.draw(app.REFRESH, self.ready6, unchanged=True),
                         [["label", "value"]])

    def test_after_a_failed_draw_even_a_still_frame_goes_out_in_full(self):
        self.draw(0)
        self.bar.failing = True
        self.draw(0.5, self.ready6)
        self.bar.failing = False
        visible, wipes = self.draw(0.5 + app.RETRY, self.ready6, unchanged=True)
        self.assertEqual(visible, ["label", "value"])
        self.assertEqual(sorted(visible + wipes), sorted(app.SLOTS))
        renders = self.renders
        self.assertEqual(self.draw(0.6 + app.RETRY, self.ready6, unchanged=True), [])
        self.assertEqual(self.renders, renders)

    def test_a_blinking_time_sends_only_the_part_that_blinks(self):
        ctrl = app.Controller(app.default_config())
        ctrl.handle("ok", T0)                                    # WORK 0:20, minutes
        sent = []
        for i in range(31):                                      # 3 s at 10 Hz
            t = round(i * 0.1, 1)
            for draw in self.draw(t, app.render(ctrl, T0 + t),
                                  unchanged=not app.changes_by_itself(ctrl)):
                sent.append((t, draw))
        self.assertEqual(sorted(sent[0][1] + sent[1][1]), sorted(app.SLOTS))   # the first draw
        self.assertEqual(sent[2:], [(0.5, ["c3"]), (1.0, ["c3"]), (1.5, ["c3"]),
                                    (2.0, ["c3"]), (2.5, ["c3"]), (3.0, ["c3"])])
        ctrl.handle("ok", T0 + 3.05)                             # on to the seconds: all lit
        self.assertEqual(self.draw(3.1, app.render(ctrl, T0 + 3.1)), [])
        self.assertEqual(self.draw(3.5, app.render(ctrl, T0 + 3.5)), [])
        self.assertEqual(self.draw(3.6, app.render(ctrl, T0 + 3.6)), [["c0", "c1"]])


class ChangesByItselfTest(unittest.TestCase):
    def still_screens(self):
        """(name, controller) for every kind of screen changes_by_itself()
        calls still."""
        for kind in app.MENU_TYPES:
            ctrl = app.Controller(app.default_config())
            ctrl.choice = kind
            yield "type %s" % kind, ctrl
        for kind in app.TYPES:
            ctrl = app.Controller(app.default_config())
            ctrl.cfg["last_type"], ctrl.field = kind, "rounds"
            yield "%s rounds" % kind, ctrl
            ctrl = app.Controller(app.default_config())
            ctrl.cfg["last_type"], ctrl.screen = kind, app.SUMMARY
            yield "summary %s" % kind, ctrl
        for field in app.SETTINGS_FIELDS:
            ctrl = app.Controller(app.default_config())
            ctrl.field = field
            yield "settings %s" % field, ctrl
        for pending_stop in (False, True):
            ctrl = app.Controller(app.default_config())
            ctrl.cfg["get_ready"] = 0
            ctrl.cfg["types"][TABATA].update(work=1, rest=1, rounds=1)
            ctrl.start(T0)
            if pending_stop:
                ctrl.handle("back", T0 + 0.5)            # STOP?, unanswered
            ctrl.update(T0 + 1)                          # ends by itself
            ctrl.handle(app.Wheel(1, T0 + 1.5, False), T0 + 1.5)   # picks a page
            self.assertEqual(ctrl.screen, app.RECAP)
            self.assertEqual(ctrl.stop_until is not None, pending_stop)
            yield "recap, STOP? pending %s" % pending_stop, ctrl

    def test_a_still_screen_renders_the_same_at_any_time(self):
        t = T0 + 2
        for name, ctrl in self.still_screens():
            with self.subTest(name):
                self.assertFalse(app.changes_by_itself(ctrl))
                frame = app.render(ctrl, t)
                for later in (t + 0.5, t + 7.3):
                    ctrl.update(later)
                    self.assertEqual(app.render(ctrl, later), frame)

    def test_only_times_being_set_among_menu_fields(self):
        for kind in app.TYPES:
            for field in ("type",) + TYPE_FIELDS[kind] + app.SETTINGS_FIELDS:
                for part in (MINUTES, SECONDS):
                    with self.subTest(kind=kind, field=field, part=part):
                        c = app.Controller(app.default_config())
                        c.cfg["last_type"], c.field, c.part = kind, field, part
                        self.assertEqual(app.changes_by_itself(c), field in TIME_FIELDS)

    def test_the_other_screens_are_as_before(self):
        h = Hand(kind=FIX_WORK, work=2)
        h.c.cfg["get_ready"] = 0
        h.c.cfg["types"][FIX_WORK]["rounds"] = 1
        h("ok", "ok", "ok", "ok")
        self.assertEqual((h.spot, app.changes_by_itself(h.c)), (SUMMARY, False))
        h("start")
        self.assertEqual((h.spot, app.changes_by_itself(h.c)), (RUN, True))
        h.wait(3.0)
        self.assertEqual((h.spot, app.changes_by_itself(h.c)), (RECAP, True))
        h("ok", gap=2.0)
        self.assertEqual(app.changes_by_itself(h.c), False)          # a page picked
        h("back", "ok")
        self.assertEqual((h.spot, app.changes_by_itself(h.c)), (("work", MINUTES), True))

if __name__ == "__main__":
    unittest.main()
