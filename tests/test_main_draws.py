"""main() end to end, as the bar sees it: a stub bar that keeps what it was
sent, a scripted input stream, and a clock that moves only when the loop
waits (support.run_main). After every pass the bar must show the frame
render() gives for that pass, also when the screen changes without input
(main() skips building the frame on still screens). Then what main() sends
while a time is set (only the part that blinks, on time), with START and
held messages in the menu, and around BACK in SETTINGS (a redraw on its
press and release, one save)."""
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import tearDownModule  # noqa: E402,F401  (first: guards the real settings)
from support import (BAR0, LIT_AFTER_DETENT, LIT_AFTER_PRESS, SUMMARY_PRESSES, T0,  # noqa: E402
                     Held, bar_message, line_of, run_main, secs, spec_hidden, spot)
import app  # noqa: E402
from app import MENU, RECAP, RUN, SETTINGS, TABATA, Wheel  # noqa: E402


def short_tabata(work, rest, rounds):
    cfg = app.default_config()
    cfg["types"][app.TABATA].update(work=work, rest=rest, rounds=rounds)
    cfg["get_ready"] = 0
    return cfg


class MainLoopDrawTest(unittest.TestCase):
    def test_a_still_menu_is_only_refreshed(self):
        run = run_main([], end=300)
        self.assertEqual(run.wrong, [])
        draws = run.draw_times
        self.assertEqual(draws[:2], [0, 0])                  # visible, then wipes
        self.assert_refreshes_only(draws[1:])
        self.assertEqual(len(draws), 2 + 58)    # ~REFRESH + a pass apart

    def assert_refreshes_only(self, draws):
        """One draw each refresh: REFRESH s apart, or a pass more (the loop
        notices on its next pass)."""
        for a, b in zip(draws, draws[1:]):
            self.assertTrue(app.REFRESH - 1e-6 <= b - a <= app.REFRESH + app.TICK + 1e-6,
                            (a, b))

    def test_screens_that_change_without_input_are_drawn_on_that_pass(self):
        # STOP? runs out on RUN; the workout ends into RECAP; the recap pages
        # by itself, then OK picks a page and it stands still.
        events = SUMMARY_PRESSES + [(1, "start"), (1.5, "back"), (1.6, ("release", "back")),
                               (20.05, "ok")]
        run = run_main(events, end=40, cfg=short_tabata(5, 3, 2))
        self.assertEqual(run.wrong, [])
        draws = run.draw_times
        self.assertIn(4.5, draws)               # STOP? gone, 3 s after BACK
        self.assertIn(17, draws)                # 2 x (5 + 3) s: RECAP
        self.assertIn(20, draws)                # its second page
        self.assertIn(20.05, draws)             # OK: the page picked
        self.assert_refreshes_only([t for t in draws if t >= 20.05][1:])

    def test_a_time_being_set_is_drawn_as_it_blinks(self):
        run = run_main([(1, "ok")], end=4.2)               # WORK's minutes from 1 s
        self.assertEqual(run.wrong, [])
        self.assertEqual(run.draw_times, [0, 0, 1, 1, 1.5, 2, 2.5, 3, 3.5, 4])

    def test_back_and_the_wheel_in_the_menu(self):
        events = [(1, app.Wheel(1, T0 + 1, False)), (2, "ok"), (2.1, app.Wheel(2, T0 + 2.1, False)),
                  (3, "back"), (3.1, ("release", "back")), (9, "back"), (9.2, ("release", "back"))]
        self.assertEqual(run_main(events, end=15).wrong, [])


# --- a time being set --------------------------------------------------------

class MainLoopBlinkTest(unittest.TestCase):
    def blink_draws(self, draws, after, before=app.REFRESH):
        """The draws strictly between `after` and the first refresh, as
        (time, ids, all blank)."""
        return [(t, sorted(el["id"] for el in els), all(app.is_blank(el) for el in els))
                for t, els in draws if after < t < before]

    def assert_blinks(self, got, slots, first_off, until=app.REFRESH):
        """`got` is one draw per half second from `first_off`, alternately
        wiping and redrawing exactly `slots`."""
        want_times = []
        t = first_off
        while t < until - 1e-6:
            want_times.append(t)
            t += 0.5
        self.assertEqual(len(got), len(want_times), got)
        for i, ((t, ids, blank), due) in enumerate(zip(got, want_times)):
            self.assertEqual(ids, sorted(slots), (t, ids))
            self.assertEqual(blank, i % 2 == 0, (t, ids))       # off first, then on
            self.assertTrue(due - 1e-6 <= t <= due + app.TICK + 1e-6, (t, due))

    def test_single_digit_minutes_send_only_c3(self):
        run = run_main([(1.0, "ok")], end=4.95, cfg=app.default_config())
        self.assertEqual(run.wrong, [])
        self.assert_blinks(self.blink_draws(run.draws, after=1.0), {"c3"}, 1.0 + LIT_AFTER_PRESS)

    def test_two_digit_minutes_send_c3_and_c4(self):
        cfg = app.default_config()
        cfg["types"][TABATA]["work"] = secs("12:34")
        run = run_main([(1.0, "ok")], end=4.95, cfg=cfg)
        self.assertEqual(run.wrong, [])
        self.assert_blinks(self.blink_draws(run.draws, after=1.0), {"c3", "c4"},
                           1.0 + LIT_AFTER_PRESS)

    def test_the_seconds_send_c0_and_c1(self):
        run = run_main([(1.0, "ok"), (1.2, "ok")], end=4.95, cfg=app.default_config())
        self.assertEqual(run.wrong, [])
        self.assert_blinks(self.blink_draws(run.draws, after=1.2), {"c0", "c1"},
                           1.2 + LIT_AFTER_PRESS)

    def test_turning_sends_only_the_changed_digit_and_no_blink(self):
        events = [(1.0, "ok")] + [(1.3 + 0.3 * i, Wheel(1, BAR0 + 1.3 + 0.3 * i, False))
                                  for i in range(5)]           # 1:20 .. 5:20, last at 2.5
        run = run_main(events, end=4.95, cfg=app.default_config())
        draws = run.draws
        self.assertEqual(run.wrong, [])
        turning = self.blink_draws(draws, after=1.0, before=2.6)
        self.assertEqual([(ids, blank) for _, ids, blank in turning], [(["c3"], False)] * 5)
        texts = [els[0]["text"] for t, els in draws if 1.0 < t < 2.6]
        self.assertEqual(texts, ["1", "2", "3", "4", "5"])
        self.assert_blinks(self.blink_draws(draws, after=2.6), {"c3"}, 2.5 + LIT_AFTER_DETENT)

    def test_a_still_rounds_field_is_only_refreshed(self):
        run = run_main([(1.0, "ok"), (1.1, "ok"), (1.2, "ok"), (1.3, "ok"), (1.4, "ok")],
                       end=4.95, cfg=app.default_config())
        self.assertEqual(run.wrong, [])
        self.assertEqual([t for t in run.draw_times if t > 1.4], [])


class PartBlinkChecks:
    """For a TestCase: the part being set, as the bar shows it pass by pass."""

    def assert_part_blinks(self, states, start, end, slots, anchor, detent):
        """On every pass in [start, end), the bar shows `slots` exactly when
        SPEC 6 says, counted from `anchor`. Passes within 1 ms of a change
        aren't checked (the loop may see it a pass late)."""
        first = LIT_AFTER_DETENT if detent else LIT_AFTER_PRESS
        checked = 0
        for t, slots_shown in states:
            if not start <= t < end:
                continue
            since = t - anchor
            if since > first - 1e-3 and abs((since - first + 0.25) % 0.5 - 0.25) < 1e-3:
                continue
            off = spec_hidden("part", since, detent) is not None
            self.assertEqual(not (set(slots) & set(slots_shown)), off, (t, slots_shown))
            self.assertTrue(set(slots) <= set(slots_shown) or off, (t, slots_shown))
            checked += 1
        self.assertGreater(checked, 5)

    def blink_draws(self, draws, after, before, slots):
        """The draws in (after, before): each must hold exactly `slots`,
        alternately all blank and all drawn. Returns their times."""
        out, blank_next = [], None
        for t, els in draws:
            if after < t < before:
                self.assertEqual(sorted(el["id"] for el in els), sorted(slots), (t, els))
                blank = all(app.is_blank(el) for el in els)
                self.assertTrue(blank or not any(app.is_blank(el) for el in els), (t, els))
                if blank_next is not None:
                    self.assertEqual(blank, blank_next, (t, els))
                blank_next = not blank
                out.append((t, blank))
        return out

    def assert_due(self, got, due):
        self.assertEqual(len(got), len(due), (got, due))
        for t, d in zip(got, due):
            self.assertTrue(d - 1e-6 <= t <= d + app.TICK + 1e-6, (t, d))


class MainLoopTimePartsTest(PartBlinkChecks, unittest.TestCase):
    def test_back_to_rounds_then_into_rest_s_seconds(self):
        # BACK at 1.0 (ROUNDS), BACK at 1.7 (REST's seconds): the seconds are
        # off from 2.2, not from 1.5. Reclaims end 1 s after the last release.
        events = SUMMARY_PRESSES + [(1.0, "back"), (1.1, ("release", "back")),
                                    (1.7, "back"), (1.8, ("release", "back"))]
        run = run_main(events, end=7.5, cfg=app.default_config())
        draws, wrong, states = run.draws, run.wrong, run.states
        self.assertEqual(wrong, [])
        self.assert_part_blinks(states, 1.7, 7.5, {"c0", "c1"}, anchor=1.7, detent=False)
        for t, slots_shown in states:
            if 1.7 <= t < 7.5:
                self.assertEqual({s: slots_shown.get(s) for s in ("c2", "c3")},
                                 {"c2": ":", "c3": "0"}, t)
        got = self.blink_draws(draws, 3.05, 7.5, {"c0", "c1"})
        self.assertTrue(got[0][1])                             # off first
        self.assert_due([t for t, _ in got], [3.2, 3.7, 4.2, 4.7, 5.2, 5.7, 6.2, 6.7, 7.2])

    def test_back_to_the_minutes_with_a_late_release(self):
        # The release at 2.45 must not restart the blink: off from 2.5.
        events = [(1.0, "ok"), (1.4, "ok"), (2.0, "back"), (2.45, ("release", "back"))]
        run = run_main(events, end=7.9, cfg=app.default_config())
        draws, wrong, states = run.draws, run.wrong, run.states
        self.assertEqual(wrong, [])
        self.assert_part_blinks(states, 2.0, 7.9, {"c3"}, anchor=2.0, detent=False)
        got = self.blink_draws(draws, 3.65, 7.9, {"c3"})
        self.assert_due([t for t, _ in got], [4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5])

    def test_a_wrap_changes_the_width_then_only_the_minutes_blink(self):
        events = [(1.0, "ok"), (1.3, Wheel(-1, BAR0 + 1.3, False)),
                  (3.0, Wheel(1, BAR0 + 3.0, False))]
        run = run_main(events, end=4.95, cfg=app.default_config())
        draws, wrong, states = run.draws, run.wrong, run.states
        self.assertEqual(wrong, [])
        at = dict(states)
        self.assertEqual([at[t] for t in sorted(at) if 1.3 <= t < 2.3][0],
                         {"c0": "0", "c1": "2", "c2": ":", "c3": "9", "c4": "5"})
        self.assert_part_blinks(states, 1.3, 3.0, {"c3", "c4"}, anchor=1.3, detent=True)
        self.assertEqual([at[t] for t in sorted(at) if 3.0 <= t < 4.0][0],
                         {"c0": "0", "c1": "2", "c2": ":", "c3": "0"})   # c4 wiped
        self.assert_part_blinks(states, 3.0, 4.95, {"c3"}, anchor=3.0, detent=True)
        got = self.blink_draws(draws, 3.05, 4.95, {"c3"})
        self.assert_due([t for t, _ in got], [4.0, 4.5])

    def test_a_held_burst_through_0(self):
        cfg = app.default_config()
        cfg["types"][TABATA]["work"] = secs("58:03")
        events = [(1.0, "ok"), (1.3, Wheel(3, BAR0 + 1.3, True))]
        run = run_main(events, end=4.95, cfg=cfg)
        draws, wrong, states = run.draws, run.wrong, run.states
        self.assertEqual(wrong, [])
        at = dict(states)
        self.assertEqual([at[t] for t in sorted(at) if t >= 1.3][0],
                         {"c0": "5", "c1": "0", "c2": ":", "c3": "1"})   # 1:05
        self.assert_part_blinks(states, 1.3, 4.95, {"c3"}, anchor=1.3, detent=True)
        self.assert_due([t for t, _ in self.blink_draws(draws, 1.35, 4.95, {"c3"})],
                        [2.3, 2.8, 3.3, 3.8, 4.3, 4.8])

    def test_a_long_session_always_shows_what_render_gives(self):
        # Every part forward and back, wraps live and held, a run with STOP?,
        # the recap and SETTINGS, at seeded uneven speeds; BACK with its release.
        script = ["ok", -1, 1, Held(3), "ok", 1, ("release", "ok"), "ok", Held(-61), "ok",
                  -1, "ok", 1, "ok", "back", "back", 1, "back", 1, "back", "back", -1,
                  "back", "ok", "ok", "ok", "ok", "ok", "ok", "start", 6.0, "back", "back",
                  1.5, "back", -1, "ok", "back", 1, "ok", "ok", Held(-2), "ok", "start",
                  "ok", "back"]
        rng = random.Random(6102026)
        t, events = 0.5, []
        for e in script:
            if isinstance(e, float):
                t += e
                continue
            t += rng.choice((0.05, 0.12, 0.3, 0.6, 1.1))
            if isinstance(e, int):
                e = Wheel(e, BAR0 + t, False)
            elif isinstance(e, Held):
                e = Wheel(e.delta, BAR0 + t, True)
            events.append((t, e))
            if e == "back":
                t += rng.choice((0.05, 0.1, 0.2))
                events.append((t, ("release", "back")))
        visited = set()
        handle = app.Controller.handle

        def spy(c, event, now):
            handle(c, event, now)
            visited.add(spot(c))
        with mock.patch.object(app.Controller, "handle", spy):
            run = run_main(events, end=t + 6, cfg=app.default_config())
            draws, wrong, states = run.draws, run.wrong, run.states
        self.assertEqual(wrong, [])
        for where in line_of(TABATA)[1:] + [RUN, RECAP, ("type", SETTINGS), "get_ready"]:
            self.assertIn(where, visited)


# --- START and held messages in the menu -------------------------------------

def bar_frame(t, events):
    """A message at `t` s after T0, decoded, as main() gets it from the listener."""
    ms = round((BAR0 + t) * 1000)
    return [(t, e) for e in app.decode_input(bar_message(events, stamp_ms=ms))]


class MainLoopStartAndHeldTest(PartBlinkChecks, unittest.TestCase):
    def test_start_in_the_menu_changes_nothing_the_bar_is_sent(self):
        # START (and its release) while WORK's minutes are lit, off, lit
        # after a detent and off again: the same draws, at the same times.
        base = [(1.0, "ok"), (2.7, Wheel(1, BAR0 + 2.7, False))]
        # On the loop's 0.1 s beat, so the passes (and draw times) stay put.
        starts = [(1.3, "start"), (1.4, ("release", "start")), (1.7, "start"),
                  (1.8, ("release", "start")), (3.1, "start"), (3.5, "start"),
                  (3.9, "start"), (4.0, ("release", "start"))]
        plain = run_main(base, end=4.95, cfg=app.default_config()).draws
        run = run_main(base + starts, end=4.95, cfg=app.default_config())
        draws, wrong, states = run.draws, run.wrong, run.states
        self.assertEqual(wrong, [])
        self.assertEqual(draws, plain)
        self.assert_part_blinks(states, 1.0, 2.7, {"c3"}, anchor=1.0,
                                        detent=False)
        self.assert_part_blinks(states, 2.7, 4.95, {"c3"}, anchor=2.7,
                                        detent=True)
        got = self.blink_draws(draws, 1.05, 4.95, {"c3"})
        self.assert_due([t for t, _ in got], [1.5, 2.0, 2.5, 2.7, 3.7, 4.2, 4.7])

    def test_start_saves_the_turned_value(self):
        for with_start in (True, False):
            with self.subTest(with_start=with_start):
                saves = []
                original = app.Controller.saved

                def spy(c):
                    saves.append((round(app.time.monotonic() - T0, 3),
                                  c.cfg["types"][TABATA]["work"]))
                    original(c)
                events = [(1.0, "ok"), (1.3, Wheel(1, BAR0 + 1.3, False))]
                if with_start:
                    events += [(2.0, "start"), (2.1, ("release", "start"))]
                with mock.patch.object(app.Controller, "saved", spy):
                    run_main(events, end=3.0, cfg=app.default_config())
                self.assertEqual(saves, [(2.0, 80)] if with_start else [])

    def test_turn_ok_turn_in_one_message(self):
        events = [(1.0, "ok")] + bar_frame(2.0, [1, "ok", ("release", "ok"), 1])
        run = run_main(events, end=4.95, cfg=app.default_config())
        draws, wrong, states = run.draws, run.wrong, run.states
        self.assertEqual(wrong, [])
        at = dict(states)
        self.assertEqual([at[t] for t in sorted(at) if t >= 2.0][0],
                         {"c0": "5", "c1": "2", "c2": ":", "c3": "1"})   # 1:25
        self.assert_part_blinks(states, 2.0, 4.95, {"c0", "c1"}, anchor=2.0,
                                        detent=True)

    def test_turn_back_turn_in_one_message_is_reclaimed(self):
        # WORK's seconds +1 (0:25), BACK, minutes -1 (59:25), BACK to TYPE,
        # the TYPE wheel +1: FIXED REST. The firmware clears the screen on
        # each BACK; on every pass the bar must show what render() gives.
        events = [(1.0, "ok"), (1.3, "ok")] + bar_frame(
            2.0, [1, "back", ("release", "back"), -1, "back", ("release", "back"), 1])
        run = run_main(events, end=4.0, cfg=app.default_config())
        draws, wrong = run.draws, run.wrong
        self.assertEqual(wrong, [])
        values = [el["text"] for t, els in draws if t >= 2.0 for el in els
                  if el["id"] == "value" and not app.is_blank(el)]
        self.assertEqual(set(values), {"FIXED REST"})


# --- BACK in SETTINGS --------------------------------------------------------

def turn_at(t, delta, held=False):
    return (t, Wheel(delta, T0 + t, held))


# TYPE -> SETTINGS (from TABATA, one detent back) -> GET READY -> SOUND
TO_SOUND = [turn_at(1, -1), (2, "ok"), (3, "ok")]


class MainLoopSettingsBackTest(unittest.TestCase):
    def test_back_redraws_on_press_and_release_and_saves_once(self):
        events = TO_SOUND + [turn_at(4, 1), (5, "back"), (5.15, ("release", "back"))]
        run = run_main(events, end=12, cfg=app.default_config())
        c, draws, saves, wrong = run.ctrl, run.draw_times, run.saves, run.wrong
        self.assertEqual(wrong, [])                       # the bar always shows render()
        self.assertIn(5, draws)                           # on the press
        self.assertIn(5.15, draws)                        # and on the release
        self.assertEqual([t for t, _ in saves], [5])      # on the BACK, not again on exit
        self.assertFalse(saves[0][1]["sound"])
        self.assertEqual((c.screen, c.field, c.choice), (MENU, "type", SETTINGS))

    def test_back_without_a_change_saves_nothing(self):
        events = TO_SOUND + [(5, "back"), (5.1, ("release", "back"))]
        run = run_main(events, end=8, cfg=app.default_config())
        c, saves, wrong = run.ctrl, run.saves, run.wrong
        self.assertEqual((wrong, saves), ([], []))
        self.assertEqual((c.screen, c.field, c.choice), (MENU, "type", SETTINGS))

    def test_a_burst_of_backs_in_one_message(self):
        burst = [(5, "back"), (5, ("release", "back"))] * 3
        events = TO_SOUND + [turn_at(4, 1)] + burst + [(6, "ok")]
        run = run_main(events, end=9, cfg=app.default_config())
        c, saves, wrong = run.ctrl, run.saves, run.wrong
        self.assertEqual(wrong, [])
        self.assertEqual([t for t, _ in saves], [5])
        self.assertEqual((c.screen, c.field, c.choice), (MENU, "get_ready", SETTINGS))

    def test_a_long_back_press_then_the_wheel(self):
        events = TO_SOUND + [(5, "back"), (6.5, ("release", "back")), turn_at(7, 1), (8, "ok")]
        run = run_main(events, end=10, cfg=app.default_config())
        c, draws, saves, wrong = run.ctrl, run.draw_times, run.saves, run.wrong
        self.assertEqual(wrong, [])
        self.assertIn(6.5, draws)
        self.assertEqual((c.screen, c.field, c.choice, c.kind), (MENU, "work", TABATA, TABATA))
        self.assertEqual([s[1]["sound"] for s in saves], [])   # nothing changed


if __name__ == "__main__":
    unittest.main()
