"""Rendering: fixed element ids, ASCII text, ink inside 72x16, screen
details, a time being set (only its part blinks, nothing shifts) and the
summary at its widest."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import tearDownModule  # noqa: E402,F401  (first: guards the real settings)
from support import OFF, REPO, T0, Hand, clock_parts, secs  # noqa: E402
sys.path.insert(0, os.path.join(REPO, "tools"))
import app  # noqa: E402
from app import (FIX_REST, FIX_WORK, MINUTES, SECONDS, SUMMARY, TABATA, Wheel,  # noqa: E402
                 Workout)
import gallery  # noqa: E402
import screen  # noqa: E402

HAVE_ATLAS = os.path.exists(screen.ATLAS_PATH)   # reference/ is local-only


def by_id(elements):
    return {el["id"]: el for el in elements}


def shown(el):
    """True unless the slot is blanked."""
    if el["type"] == "text":
        return el["text"].strip() != ""
    return el["x"] < app.W and el["y"] < app.H


def around(ink):
    """The pixels and their eight neighbours: ink of another text there would
    touch it, so the two would read as one."""
    return {(x + dx, y + dy) for x, y in ink for dx in (-1, 0, 1) for dy in (-1, 0, 1)}


def time_text(els):
    """The time as shown: its clock characters, left to right."""
    return "".join(els[slot]["text"] for slot in reversed(app.CLOCK_SLOTS)
                   if slot in els and shown(els[slot]))


def running(kind=TABATA, t=8.5, pause_at=None, **kw):
    w = Workout(kind, **{"work": 20, "rest": 10, "rounds": 8, "get_ready": 5, **kw})
    w.start(T0)
    if pause_at is not None:
        w.toggle_pause(T0 + pause_at)
    w.update(T0 + t)
    return w


class FrameInvariantsTest(unittest.TestCase):
    def frames(self):
        return [(name, make()) for name, make in gallery.STATES]

    def test_same_ids_in_same_order_every_frame(self):
        for name, els in self.frames():
            with self.subTest(name):
                self.assertEqual([el["id"] for el in els], list(app.SLOTS))
                self.assertEqual([el["z_index"] for el in els], list(range(len(app.SLOTS))))

    def test_every_slot_keeps_one_element_type(self):
        # The bar refuses (HTTP 400) a draw that changes an id's type.
        kinds = {}
        for name, els in self.frames():
            for el in els:
                kinds.setdefault(el["id"], set()).add(el["type"])
        for eid, types in kinds.items():
            with self.subTest(eid):
                self.assertEqual(len(types), 1, types)
                self.assertEqual(types.pop() == "rectangle", eid in app.RECT_SLOTS)

    def test_nothing_relies_on_align(self):
        # The bar and the emulator round `align` centring differently for odd
        # widths, so positions are computed here instead.
        for name, els in self.frames():
            for el in els:
                self.assertNotIn("align", el, "%s: %s" % (name, el["id"]))

    def test_blank_rectangles_are_off_screen_and_transparent(self):
        for eid in app.RECT_SLOTS:
            el = app.blank(eid)
            self.assertEqual((el["x"], el["y"], el["width"], el["height"]), (app.W, app.H, 1, 1))
            self.assertTrue(el["fill_colors"][0].endswith("00"))

    def test_frame_refuses_the_wrong_type_for_a_slot(self):
        with self.assertRaises(ValueError):
            app.frame({"bar": app.text("bar", "X")})
        with self.assertRaises(ValueError):
            app.frame({"value": app.rect("value", 0, 0, 1, 1, "#FFFFFFFF")})

    def test_text_is_printable_ascii_and_colours_are_rrggbbaa(self):
        for name, els in self.frames():
            for el in els:
                with self.subTest(name, id=el["id"]):
                    if el["type"] == "text":
                        self.assertTrue(el["text"] and all(" " <= c <= "~" for c in el["text"]))
                    for c in [el.get("color")] + list(el.get("fill_colors", [])):
                        if c is not None:
                            self.assertRegex(c, r"^#[0-9A-Fa-f]{8}$")

    @unittest.skipUnless(HAVE_ATLAS, "needs reference/busybar-emulator for the font atlas")
    def test_ink_stays_on_screen_and_texts_keep_a_gap(self):
        for name, els in self.frames():
            with self.subTest(name):
                inks = {}
                for el in els:
                    if el["type"] != "text" or not shown(el):
                        continue
                    w, h, lit, _ = screen.rasterize(el["text"], el["font"])
                    dx, dy = screen.anchor(el, w, h)
                    ink = {(dx + x, dy + y) for x, y in lit}
                    off = [p for p in ink if not (0 <= p[0] < app.W and 0 <= p[1] < app.H)]
                    self.assertEqual(off, [], "%s: ink off screen" % el["id"])
                    inks[el["id"]] = ink
                ids = sorted(inks)
                for i, a in enumerate(ids):
                    for b in ids[i + 1:]:
                        self.assertFalse(inks[a] & around(inks[b]),
                                         "%s touches %s" % (a, b))


class ScreenDetailsTest(unittest.TestCase):
    def test_fixed_phase_has_a_bar_open_phase_has_none(self):
        els = by_id(app.render_workout(running(t=15), T0 + 15))       # WORK 10 s left
        self.assertEqual(els["bar"]["width"], 36)
        self.assertTrue(shown(els["bar_bg"]))
        self.assertFalse(shown(els["note"]))
        w = running(FIX_REST, t=47)
        els = by_id(app.render_workout(w, T0 + 47))
        self.assertEqual(time_text(els), "+0:42")
        self.assertFalse(shown(els["note"]))                 # no OK hint
        self.assertFalse(shown(els["bar"]) or shown(els["bar_bg"]))

    def test_bar_loses_one_nth_per_displayed_second(self):
        def widths(start, seconds):
            w = running(t=start + 0.05)
            return [by_id(app.render_workout(w, T0 + start + i + 0.5))["bar"]["width"]
                    for i in range(seconds)]
        # 72 * s / N columns, rounded up: full at the start, a sliver at the end.
        self.assertEqual(widths(5, 20), [72, 69, 65, 62, 58, 54, 51, 47, 44, 40,
                                         36, 33, 29, 26, 22, 18, 15, 11, 8, 4])
        self.assertEqual(widths(0, 5), [72, 58, 44, 29, 15])          # get-ready
        self.assertEqual(by_id(app.render_workout(running(t=0.4), T0 + 0.4))["bar"]["fill_colors"],
                         [app.COLOR_READY])

    def test_bar_is_full_at_the_start_and_never_empty_before_the_end(self):
        # The shortest and longest phases and ones that don't divide 72.
        for work in (1, 2, 7, 13, 3595):
            with self.subTest(work=work):
                w = running(t=0, work=work, get_ready=0)
                self.assertEqual(by_id(app.render_workout(w, T0))["bar"]["width"], 72)
                last = T0 + work - 0.001                 # 1 ms before WORK ends
                w.update(last)
                self.assertEqual(w.phase, app.WORK)
                els = by_id(app.render_workout(w, last))
                self.assertTrue(shown(els["bar"]))
                self.assertEqual(els["bar"]["width"], math.ceil(72 / work))
                w.update(T0 + work)                      # REST starts full
                self.assertEqual(by_id(app.render_workout(w, T0 + work))["bar"]["width"], 72)

    def test_bar_stands_still_while_paused_and_carries_on_after(self):
        w = running(t=12.3, pause_at=12.3)               # WORK, 7.3 s in: shows 0:13
        frozen = by_id(app.render_workout(w, T0 + 12.3))["bar"]
        self.assertEqual(frozen["width"], math.ceil(72 * 13 / 20))
        self.assertEqual(frozen["fill_colors"], [app.COLOR_PAUSED])
        for later in (0.6, 1.0, 30.0, 3600.0):
            w.update(T0 + 12.3 + later)
            self.assertEqual(by_id(app.render_workout(w, T0 + 12.3 + later))["bar"]["width"],
                             frozen["width"])
        back = T0 + 3612.3
        w.toggle_pause(back)
        self.assertEqual(by_id(app.render_workout(w, back + 0.69))["bar"]["width"],
                         math.ceil(72 * 13 / 20))       # still in the same second
        resumed = by_id(app.render_workout(w, back + 0.71))["bar"]   # now 0:12
        self.assertEqual(resumed["width"], math.ceil(72 * 12 / 20))
        self.assertEqual(resumed["fill_colors"], [app.COLOR_WORK])

    def frame_changes(self, kind, phase_start, duration, **kw):
        """Render a fixed phase at 10 Hz, as main() does; for every frame that
        differs from the one before: (displayed seconds before, after)."""
        w = running(kind, t=phase_start + 0.01, **kw)
        phase = w.phase
        changes, before = [], None
        for tick in range(duration * 10):
            now = T0 + phase_start + tick / 10 + 0.01
            w.update(now)
            self.assertEqual(w.phase, phase)
            seconds, els = w.display_seconds(now), app.render_workout(w, now)
            if before is not None and els != before[1]:
                changes.append((before[0], seconds))
            before = (seconds, els)
        return changes

    def test_a_fixed_phase_redraws_once_per_displayed_second(self):
        cases = [("work 20 s", (TABATA, 5, 20), {}),
                 ("get ready 5 s", (TABATA, 0, 5), {}),
                 ("fixed work 600 s", (FIX_WORK, 5, 600), {"work": 600})]
        for name, args, kw in cases:
            with self.subTest(name):
                changes = self.frame_changes(*args, **kw)
                ticks = [c for c in changes if c[0] != c[1]]
                blinks = [c for c in changes if c[0] == c[1]]
                self.assertEqual(len(ticks), args[2] - 1)          # once per second
                # Otherwise only the last digit blinking off, mid-second.
                self.assertEqual(sorted(s for s, _ in blinks), [1, 2, 3])

    def test_the_time_stands_still(self):
        # Each character keeps its place as the seconds tick by, whatever the
        # digits (a 1 is narrower than the others in extra_large).
        def places(w, t):
            els = by_id(app.render_workout(w, T0 + t))
            return {slot: els[slot]["x"] - (2 if els[slot]["text"] == "1" else 0)
                    for slot in app.CLOCK_SLOTS if shown(els[slot])}
        seen = {tuple(sorted(places(running(t=t), t).items())) for t in (11.5, 12.5, 13.5, 14.5, 15.5)}
        self.assertEqual(len(seen), 1)                     # 0:14, 0:13, 0:12, 0:11, 0:10
        long = running(t=5.5, work=620)                    # 10:20 down to 9:59
        before, after = places(long, 5.5), places(long, 5 + 21.5)
        self.assertEqual(time_text(by_id(app.render_workout(long, T0 + 26.5))), "9:59")
        for slot in ("c0", "c1", "c2", "c3"):              # the seconds and 1 minute
            self.assertEqual(before[slot], after[slot])

    def test_menu_times_and_rounds_stand_still(self):
        cfg = app.default_config()
        xs = []
        for work in (20, 21, 11):
            cfg["types"][TABATA]["work"] = work
            els = by_id(app.render_menu(cfg, "work", TABATA))
            xs.append(els["c3"]["x"])
        self.assertEqual(len(set(xs)), 1)

    def test_a_workout_colon_never_moves(self):
        # Countdown and count-up, whatever the width of the minutes.
        for kind, values, t, want in (
                (TABATA, {"work": 20}, 5.5, "0:20"),
                (FIX_WORK, {"work": 90}, 5.5, "1:30"),
                (FIX_WORK, {"work": 620}, 5.5, "10:20"),
                (FIX_REST, {"rest": 90}, 5.5, "+0:00"),
                (FIX_REST, {"rest": 90}, 5.5 + 599, "+9:59"),
                (FIX_REST, {"rest": 90}, 5.5 + 600, "+10:00"),
                (FIX_REST, {"rest": 90}, 5.5 + 5999, "+99:59")):
            with self.subTest(want=want):
                els = by_id(app.render_workout(running(kind, **values), T0 + t))
                self.assertEqual(time_text(els), want)
                self.assertEqual(els["c2"]["text"], ":")
                self.assertEqual(els["c2"]["x"], app.TIME_MID_X)

    def test_the_widest_time_clears_the_widest_label_and_counter(self):
        els = by_id(app.render_workout(running(FIX_REST, rest=90), T0 + 5.5 + 5999))
        self.assertEqual(time_text(els), "+99:59")
        for txt, font in (("PAUSE", "small"), ("99/99", "condensed"), ("R1000", "condensed")):
            self.assertGreaterEqual(els["c5"]["x"], app.text_width(txt, font))

    def test_a_menu_time_keeps_its_colon_and_seconds_as_the_minutes_change_width(self):
        cfg = app.default_config()
        places = set()
        for work in (secs("0:20"), secs("9:20"), secs("10:20"), secs("59:20")):
            cfg["types"][TABATA]["work"] = work
            els = by_id(app.render_menu(cfg, "work", TABATA))
            places.add((els["c2"]["x"], els["c1"]["x"], els["c0"]["x"]))
        self.assertEqual(len(places), 1)
        self.assertEqual(places.pop()[0], app.MENU_COLON_X)

    def test_get_ready_shows_plain_seconds_and_no_round(self):
        els = by_id(app.render_workout(running(t=0.4), T0 + 0.4))
        self.assertEqual((els["label"]["text"], time_text(els)), ("READY", "5"))
        self.assertFalse(shown(els["c1"]))                   # a single digit
        self.assertFalse(shown(els["round"]))

    def test_round_counter(self):
        self.assertEqual(by_id(app.render_workout(running(t=40), T0 + 40))["round"]["text"], "2/8")
        w = running(t=5 + 11 * 30 + 3, rounds=None)
        self.assertEqual(by_id(app.render_workout(w, T0 + 5 + 11 * 30 + 3))["round"]["text"], "R12")

    def test_round_counter_is_bold_while_it_fits_under_the_label(self):
        def info(w, t):
            el = by_id(app.render_workout(w, T0 + t))["round"]
            return el["text"], el["font"]
        self.assertEqual(info(running(t=40), 40), ("2/8", "bold"))
        self.assertEqual(info(running(t=40, rounds=12), 40), ("2/12", "condensed"))
        self.assertEqual(info(running(t=40, rounds=None), 40), ("R2", "bold"))
        self.assertEqual(info(running(t=5 + 99 * 30 + 3, rounds=None), 5 + 99 * 30 + 3),
                         ("R100", "condensed"))

    def test_a_phase_begins_in_its_own_colour(self):
        els = by_id(app.render_workout(running(t=5.1), T0 + 5.1))
        self.assertEqual(time_text(els), "0:20")
        self.assertEqual(els["c0"]["color"], app.COLOR_WORK)

    def test_only_the_last_digit_blinks_in_the_last_three_seconds(self):
        def parts(t):
            els = by_id(app.render_workout(running(t=t), T0 + t))
            return shown(els["c1"]), shown(els["c0"])
        self.assertEqual([parts(t) for t in (21.1, 21.6, 22.1, 22.6, 23.4, 23.7, 24.2, 24.9)],
                         [(True, True), (True, True),    # 4 left: steady
                          (True, True), (True, False),   # 3: digit on, off
                          (True, True), (True, False),   # 2
                          (True, True), (True, False)])  # 1
        self.assertEqual(parts(25.1), (True, True))      # REST begins, steady again
        els = by_id(app.render_workout(running(t=22.1), T0 + 22.1))
        self.assertEqual(time_text(els), "0:03")
        self.assertEqual(els["c0"]["color"], app.COLOR_WORK)

    def test_get_ready_blinks_too_but_open_phases_never_do(self):
        self.assertFalse(shown(by_id(app.render_workout(running(t=2.7), T0 + 2.7))["c0"]))
        w = running(FIX_REST, t=6.8)
        self.assertTrue(shown(by_id(app.render_workout(w, T0 + 6.8))["c0"]))

    def test_paused_is_dim_and_blinks(self):
        on = by_id(app.render_workout(running(t=12.2, pause_at=12), T0 + 12.2))
        off = by_id(app.render_workout(running(t=12.7, pause_at=12), T0 + 12.7))
        self.assertEqual(on["label"]["text"], "PAUSE")
        self.assertEqual(on["c0"]["color"], app.COLOR_PAUSED)
        self.assertEqual(time_text(off), "")                             # all of it blinks
        self.assertTrue(shown(off["label"]))

    def test_stop_prompt_replaces_the_label(self):
        els = by_id(app.render_workout(running(t=9), T0 + 9, confirm_stop=True))
        self.assertEqual((els["label"]["text"], els["label"]["color"]), ("STOP?", app.COLOR_STOP))
        self.assertEqual(time_text(els), "0:16")

    def test_open_rest_counts_up(self):
        w = running(FIX_WORK, t=90.2)
        self.assertEqual(time_text(by_id(app.render_workout(w, T0 + 90.2))), "+1:05")


class MenuScreenTest(unittest.TestCase):
    @unittest.skipUnless(HAVE_ATLAS, "needs reference/busybar-emulator for the font atlas")
    def test_text_width_matches_the_atlas(self):
        every = "".join(chr(c) for c in range(32, 127))
        for font in app.ADVANCE:
            for s in (every, "59:59/59:59 x", "FIXED WORK", "a"):
                with self.subTest(font=font, s=s):
                    self.assertEqual(app.text_width(s, font), screen.text_width(s, font))

    def test_summary_text(self):
        def line(kind, **s):
            return app.summary_text(kind, {"work": 20, "rest": 10, "rounds": 8, **s})
        self.assertEqual(line(TABATA), "20/10 x")
        self.assertEqual(line(TABATA, work=90, rest=45), "1:30/0:45 x")
        self.assertEqual(line(FIX_REST, work=600), "0:10 x")       # only the timed rest
        self.assertEqual(line(FIX_REST, rest=90), "1:30 x")
        self.assertEqual(line(FIX_WORK, rest=600), "0:20 x")       # only the timed work

    def test_summary_fits_with_extra_large_or_condensed(self):
        cfg = app.default_config()
        self.assertEqual(by_id(app.render_summary(cfg))["value"]["font"], "extra_large")
        cfg["types"][TABATA].update(work=3599, rest=3599, rounds=99)
        els = by_id(app.render_summary(cfg))
        self.assertEqual(els["value"]["text"], "59:59/59:59 x99")
        self.assertEqual(els["value"]["font"], "condensed")
        self.assertEqual(app.text_width("59:59/59:59 x99", "condensed"), 70)
        self.assertLessEqual(els["value"]["x"] + 70, app.W)

    def test_unlimited_rounds_draw_infinity_after_the_text(self):
        cfg = app.default_config()
        cfg["types"][TABATA]["rounds"] = None
        els = by_id(app.render_summary(cfg))
        text_end = els["value"]["x"] + app.text_width("20/10 x", "extra_large")
        infs = [els[s] for s in app.INF_SLOTS if shown(els[s])]
        self.assertEqual(len(infs), len(app.INF_RECTS["extra_large"]))
        self.assertGreater(min(r["x"] for r in infs), text_end)
        self.assertLessEqual(max(r["x"] + r["width"] for r in infs), app.W)
        self.assertEqual(min(r["y"] for r in infs), app.ROW_VALUE)
        self.assertEqual(max(r["y"] + r["height"] for r in infs), app.H)

    def test_rounds_field_unlimited_is_only_infinity(self):
        cfg = app.default_config()
        cfg["types"][TABATA]["rounds"] = None
        els = by_id(app.render_menu(cfg, "rounds", TABATA))
        self.assertFalse(shown(els["value"]))
        self.assertTrue(shown(els["inf0"]))
        self.assertFalse(shown(els["note"]))                 # no type name: it didn't fit

    def test_infinity_art_is_covered_exactly(self):
        for font, art in app.INF_ART.items():
            with self.subTest(font):
                lit = {(x, y) for y, row in enumerate(art) for x, c in enumerate(row) if c == "#"}
                cells = [(x + i, y + j) for x, y, w, h in app.INF_RECTS[font]
                         for i in range(w) for j in range(h)]
                self.assertEqual(sorted(cells), sorted(lit))     # no gaps, no overlaps

    def test_field_values(self):
        cfg = app.default_config()
        self.assertEqual(app.field_value(cfg, "type", app.SETTINGS), ("SETTINGS", False))
        self.assertEqual(app.field_value(cfg, "work", TABATA), ("0:20", False))
        self.assertEqual(app.field_value(cfg, "get_ready", TABATA), ("5 SEC", False))
        cfg.update(get_ready=0, sound=False, step=15)
        self.assertEqual(app.field_value(cfg, "get_ready", TABATA), ("OFF", False))
        self.assertEqual(app.field_value(cfg, "sound", TABATA), ("OFF", False))
        self.assertEqual(app.field_value(cfg, "step", TABATA), ("15 SEC", False))
        self.assertEqual(app.field_value(cfg, "skip_with", TABATA), ("OK", False))
        cfg["skip_with"] = "start"
        self.assertEqual(app.field_value(cfg, "skip_with", TABATA), ("START", False))

    def test_skip_with_is_a_label_and_a_big_centred_word(self):
        cfg = app.default_config()
        for setting, word in (("ok", "OK"), ("start", "START")):
            with self.subTest(setting):
                cfg["skip_with"] = setting
                els = by_id(app.render_menu(cfg, "skip_with", TABATA))
                self.assertEqual((els["label"]["text"], els["label"]["font"]), ("SKIP WITH", "small"))
                value = els["value"]
                width = app.text_width(word, "extra_large")
                self.assertEqual((value["text"], value["font"]), (word, "extra_large"))
                self.assertLessEqual(width, app.W)
                self.assertEqual(value["x"], (app.W - width) // 2)
                self.assertFalse(any(shown(els[slot]) for slot in app.CLOCK_SLOTS))


class MenuBlinkTest(unittest.TestCase):
    """On WORK and REST the part being set blinks 0.5 s on, 0.5 s off from
    the press that reached it; after a detent it stays lit for 1 s first.
    The colon and the other part stay lit, and nothing shifts (SPEC 6)."""

    def lit(self, c, t):
        els = by_id(app.render(c, T0 + t))
        return {slot for slot in app.CLOCK_SLOTS if shown(els[slot])}

    def test_blinks_at_once_after_a_press_and_after_a_second_after_a_detent(self):
        c = app.Controller(app.default_config())
        c.handle("ok", T0)                                   # WORK 0:20, its minutes
        lit, minutes_off = {"c0", "c1", "c2", "c3"}, {"c0", "c1", "c2"}
        blink = [lit, lit, lit, minutes_off, minutes_off, lit, lit, minutes_off, lit]
        after_press = (0, 0.25, 0.49, 0.5, 0.99, 1.0, 1.49, 1.5, 2.0)
        self.assertEqual([self.lit(c, t) for t in after_press], blink)
        c.handle(Wheel(1, 500.0, False), T0 + 0.7)           # off, then a detent: lit
        self.assertEqual(c.cfg["types"][TABATA]["work"], 80)
        after_detent = (0, 0.5, 0.99, 1.0, 1.49, 1.5, 1.99, 2.0, 2.5)
        self.assertEqual([self.lit(c, 0.7 + t) for t in after_detent], blink)
        c.handle("ok", T0 + 4)                               # its seconds
        self.assertEqual([self.lit(c, 4 + t) for t in (0, 0.49, 0.5, 0.99, 1.0)],
                         [lit, lit, {"c2", "c3"}, {"c2", "c3"}, lit])

    def test_start_leaves_the_blink_alone(self):
        # The menu ignores START (SPEC 3): it neither lights a part that is
        # off nor cuts short the second lit after a detent.
        lit, minutes_off = {"c0", "c1", "c2", "c3"}, {"c0", "c1", "c2"}
        c = app.Controller(app.default_config())
        c.handle("ok", T0)                                   # WORK 0:20, its minutes
        c.handle("start", T0 + 0.6)
        self.assertEqual(self.lit(c, 0.6), minutes_off)
        c.handle(Wheel(1, 500.0, False), T0 + 2)
        c.handle("start", T0 + 2.2)
        self.assertEqual([self.lit(c, 2 + t) for t in (0.2, 0.7, 0.99, 1.0)],
                         [lit, lit, lit, minutes_off])

    def test_every_detent_of_a_turn_keeps_it_lit(self):
        # The bar holds input back up to ~0.75 s mid-turn: detents that far
        # apart keep it lit throughout.
        c = app.Controller(app.default_config())
        c.handle("ok", T0)
        for i in range(1, 11):
            t = 0.75 * i
            c.handle(Wheel(1, 500.0 + t, False), T0 + t)
            shown_time = app.fmt_time(c.cfg["types"][TABATA]["work"])
            for into in (0, 0.5, 0.74):
                self.assertEqual(self.lit(c, t + into), set(app.CLOCK_SLOTS[:len(shown_time)]),
                                 (t, into))


class RecapScreenTest(unittest.TestCase):
    def finished(self, kind=TABATA, stop_at=None, **kw):
        w = Workout(kind, **{"work": 20, "rest": 10, "rounds": 8, "get_ready": 5, **kw})
        w.start(T0)
        if stop_at is None:
            w.update(T0 + 10 ** 6)
        else:
            w.stop(T0 + stop_at)
        return w

    def values(self, w):
        return [app.recap_value(w, page) for page in app.RECAP_PAGES]

    def test_full_workout(self):
        w = self.finished()
        self.assertEqual(self.values(w), ["2:40", "1:10", "8/8", "3:50"])
        els = by_id(app.render_recap(w, "total"))
        self.assertEqual((els["label"]["text"], els["value"]["text"]), ("TOTAL", "3:50"))
        self.assertEqual((els["note"]["text"], els["note"]["color"]), ("DONE", app.COLOR_RECAP))
        self.assertEqual(els["value"]["color"], app.COLOR_RECAP)

    def test_stopped_mid_work(self):
        w = self.finished(stop_at=5 + 3 * 30 + 12)      # 12 s into round 4's WORK
        self.assertEqual(self.values(w), ["1:12", "0:30", "3/8", "1:42"])
        els = by_id(app.render_recap(w, "rounds"))
        self.assertEqual((els["note"]["text"], els["note"]["color"]), ("STOPPED", app.COLOR_STOP))

    def test_stopped_during_get_ready_is_all_zero(self):
        w = self.finished(stop_at=3)
        self.assertEqual(self.values(w), ["0:00", "0:00", "0/8", "0:00"])

    def test_unlimited_rounds_and_hours(self):
        w = self.finished(rounds=None, stop_at=5 + 6125)
        self.assertEqual(self.values(w)[2:], ["204", "1:42:05"])

    def test_open_phases_count_real_time(self):
        w = Workout(FIX_REST, rest=10, rounds=2, get_ready=0)
        w.start(T0)
        w.advance(T0 + 47.6)                             # first set: 47.6 s
        w.update(T0 + 57.6)
        w.advance(T0 + 90)                               # second set: 32.4 s
        self.assertEqual(self.values(w), ["1:20", "0:10", "2/2", "1:30"])


class PainterTest(unittest.TestCase):
    def setUp(self):
        self.p = app.Painter()
        cfg = app.default_config()
        self.ready = app.render_menu(cfg, "get_ready", TABATA)        # "5 SEC"
        cfg["get_ready"] = 6
        self.ready6 = app.render_menu(cfg, "get_ready", TABATA)
        cfg["types"][TABATA]["rounds"] = None
        self.inf = app.render_menu(cfg, "rounds", TABATA)

    def ids(self, els):
        return [el["id"] for el in els]

    def draw(self, elements, refresh=False):
        plan = self.p.plan(elements, refresh)
        for payload in plan:
            self.p.sent(payload)
        return tuple(self.ids(payload) for payload in plan)

    def test_first_draw_sends_visible_first_then_wipes_every_slot(self):
        visible, wipes = self.draw(self.ready)
        self.assertEqual(visible, ["label", "value"])
        self.assertEqual(sorted(visible + wipes), sorted(app.SLOTS))

    def test_then_only_what_changed(self):
        self.draw(self.ready)
        self.assertEqual(self.draw(self.ready6), (["value"], []))
        self.assertEqual(self.draw(self.ready6), ([], []))

    def test_refresh_resends_the_visible_elements_only(self):
        self.draw(self.ready)
        self.assertEqual(self.draw(self.ready, refresh=True), (["label", "value"], []))

    def test_a_slot_that_goes_blank_is_wiped_once(self):
        self.draw(self.inf)
        visible, wipes = self.draw(self.ready)
        self.assertEqual(visible, ["label", "value"])                # both changed
        self.assertEqual(wipes, list(app.INF_SLOTS[:len(app.INF_RECTS["extra_large"])]))
        self.assertEqual(self.draw(self.ready), ([], []))

    def test_after_forget_visible_comes_first_and_everything_is_wiped(self):
        self.draw(self.inf)
        self.p.forget()                                              # e.g. BACK
        visible, wipes = self.draw(self.ready)
        self.assertEqual(visible, ["label", "value"])
        self.assertEqual(sorted(visible + wipes), sorted(app.SLOTS))

    def test_is_blank(self):
        self.assertTrue(all(app.is_blank(app.blank(eid)) for eid in app.SLOTS))
        self.assertFalse(app.is_blank(app.rect("bar", 0, 15, 72, 1, "#FFFFFFFF")))
        self.assertFalse(app.is_blank(app.text("value", "0:20")))


class FormatTest(unittest.TestCase):
    def test_fmt_time(self):
        self.assertEqual(app.fmt_time(23), "0:23")
        self.assertEqual(app.fmt_time(23, plus=True), "+0:23")
        self.assertEqual(app.fmt_time(app.OPEN_CAP, plus=True), "+99:59")
        self.assertEqual(app.fmt_time(3595), "59:55")
        self.assertEqual(app.fmt_time(6125, hours=True), "1:42:05")
        self.assertEqual(app.fmt_time(600, hours=True), "10:00")


class RecapRoundingTest(unittest.TestCase):
    def test_phases_added_up_do_not_lose_a_second(self):
        for ms in range(0, 60000, 7):
            start = ms / 1000
            w = app.Workout(TABATA, work=5, rest=5, rounds=2, get_ready=2)
            w.start(start)
            w.update(start + 17.5)
            self.assertEqual(app.fmt_time(w.stats.work_seconds), "0:10", start)
            self.assertEqual(app.fmt_time(w.stats.total_seconds), "0:15", start)


class RenderPartsTest(unittest.TestCase):
    def test_exactly_the_part_being_set_is_left_out_and_nothing_shifts(self):
        for txt in ("0:05", "1:00", "9:59", "10:00", "59:59"):
            for kind, field in ((TABATA, "work"), (TABATA, "rest"), (FIX_REST, "rest"),
                                (FIX_WORK, "work")):
                for part in (MINUTES, SECONDS):
                    with self.subTest(txt=txt, kind=kind, field=field, part=part):
                        c = app.Controller(app.default_config())
                        c.cfg["last_type"] = kind
                        c.cfg["types"][kind][field] = secs(txt)
                        c.field, c.part, c.input_at = field, part, T0
                        on = {el["id"]: el for el in app.render(c, T0 + 0.2)}
                        off = {el["id"]: el for el in app.render(c, T0 + OFF)}
                        gone = {s for s in app.SLOTS if on[s] != off[s]}
                        self.assertEqual(gone, clock_parts(txt)[part])
                        for slot in gone:
                            self.assertTrue(app.is_blank(off[slot]))
                            self.assertFalse(app.is_blank(on[slot]))
                        drawn = "".join(on[s]["text"] for s in reversed(app.CLOCK_SLOTS)
                                        if not app.is_blank(on[s]))
                        self.assertEqual(drawn, txt)
                        self.assertEqual(on["label"]["text"], field.upper())

    def test_other_fields_never_lose_a_slot_whatever_the_part(self):
        cfg = app.default_config()
        cfg["types"][TABATA]["rounds"] = 12
        fields = ["type", "rounds", "get_ready", "sound", "step", "skip_with"]
        for field in fields:
            for part in (MINUTES, SECONDS):
                with self.subTest(field=field, part=part):
                    c = app.Controller(cfg)
                    c.field, c.part, c.input_at = field, part, T0
                    self.assertEqual(app.render(c, T0 + OFF), app.render(c, T0 + 0.2))
        c = app.Controller(app.default_config())
        c.cfg["types"][TABATA]["rounds"] = None
        c.field, c.part, c.input_at = "rounds", SECONDS, T0
        self.assertEqual(app.render(c, T0 + OFF), app.render(c, T0 + 0.2))

    def test_the_summary_never_blinks(self):
        h = Hand()("ok", "ok", "ok", "ok", "ok", "ok")
        self.assertEqual(h.spot, SUMMARY)
        h.c.part = SECONDS
        self.assertEqual(app.render(h.c, h.now + OFF), app.render(h.c, h.now + 0.2))


class SummaryWidthTest(unittest.TestCase):
    def extent(self, elements):
        xs = []
        for el in elements:
            if app.is_blank(el) or el["id"] in ("label", "note"):
                continue
            if el["type"] == "text":
                xs.append((el["x"], el["x"] + app.text_width(el["text"], el["font"])))
                self.assertGreaterEqual(el["y"] + app.INK_TOP[el["font"]], app.ROW_VALUE)
            else:
                xs.append((el["x"], el["x"] + el["width"]))
                self.assertGreaterEqual(el["y"], app.ROW_VALUE)
        return min(a for a, _ in xs), max(b for _, b in xs)

    def summary(self, kind, work, rest, rounds):
        cfg = app.default_config()
        cfg["last_type"] = kind
        cfg["types"][kind].update(work=work, rest=rest, rounds=rounds)
        return app.render_summary(cfg)

    def test_59_59_59_59_x99_and_unlimited_fit(self):
        els = {el["id"]: el for el in self.summary(TABATA, 3599, 3599, 99)}
        self.assertEqual((els["value"]["text"], els["value"]["font"]),
                         ("59:59/59:59 x99", "condensed"))
        lo, hi = self.extent(els.values())
        self.assertGreaterEqual(lo, 0)
        self.assertLessEqual(hi, app.W)
        self.assertEqual(hi - lo, 70)                          # SPEC 6
        els = self.summary(TABATA, 3599, 3599, None)
        lo, hi = self.extent(els)
        self.assertTrue(0 <= lo and hi <= app.W, (lo, hi))

    def test_every_edge_value_fits(self):
        times = (1, 3, 59, 60, 599, 600, 3540, 3599)
        for kind in app.TYPES:
            for work in times:
                for rest in times:
                    for rounds in (1, 9, 10, 99, None):
                        lo, hi = self.extent(self.summary(kind, work, rest, rounds))
                        self.assertTrue(0 <= lo and hi <= app.W,
                                        (kind, work, rest, rounds, lo, hi))


if __name__ == "__main__":
    unittest.main()
