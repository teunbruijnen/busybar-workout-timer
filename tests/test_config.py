"""Saved settings: validation, wheel steps, and loading and saving
config.json."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import tearDownModule  # noqa: E402,F401  (first: guards the real settings)
from support import secs  # noqa: E402
import app  # noqa: E402
from app import FIX_REST, FIX_WORK, TABATA, TIME_FIELDS  # noqa: E402


class CleanConfigTest(unittest.TestCase):
    def test_junk_gives_defaults(self):
        for raw in (None, [], "x", 3, {}, {"types": "nope"}):
            with self.subTest(raw=raw):
                self.assertEqual(app.clean_config(raw), app.default_config())

    def test_valid_values_are_kept(self):
        raw = app.default_config()
        raw.update(last_type=FIX_WORK, get_ready=0, sound=False, step=15, skip_with="start")
        raw["types"][FIX_REST] = {"work": 20, "rest": 90, "rounds": None}
        raw["types"][TABATA] = {"work": 3595, "rest": 5, "rounds": 99}
        self.assertEqual(app.clean_config(json.loads(json.dumps(raw))), raw)

    def test_each_bad_value_falls_back_on_its_own(self):
        raw = {"last_type": "boxing", "get_ready": 16, "sound": "yes", "step": 7,
               "skip_with": "START",
               "types": {TABATA: {"work": 0, "rest": 40, "rounds": 0},
                         FIX_REST: {"work": True, "rest": "10", "rounds": 100},
                         FIX_WORK: [1, 2]}}
        cfg = app.clean_config(raw)
        d = app.default_config()
        self.assertEqual(cfg["types"][TABATA], {"work": 20, "rest": 40, "rounds": 8})
        self.assertEqual(cfg["types"][FIX_REST], d["types"][FIX_REST])
        self.assertEqual(cfg["types"][FIX_WORK], d["types"][FIX_WORK])
        for key in ("last_type", "get_ready", "sound", "step", "skip_with"):
            self.assertEqual(cfg[key], d[key])

    def test_booleans_are_not_numbers(self):
        cfg = app.clean_config({"get_ready": True, "step": True,
                                "types": {TABATA: {"rounds": True}}})
        self.assertEqual((cfg["get_ready"], cfg["step"]), (5, 5))
        self.assertEqual(cfg["types"][TABATA]["rounds"], 8)

    def test_bad_skip_with_falls_back_to_ok(self):
        for raw, kept in (("start", "start"), ("ok", "ok"), ("START", "ok"), ("Start", "ok"),
                          ("", "ok"), ("pause", "ok"), (True, "ok"), (False, "ok"), (1, "ok"),
                          (0, "ok"), (None, "ok"), (["start"], "ok"), ({"start": 1}, "ok")):
            with self.subTest(raw=raw):
                cfg = app.clean_config({"skip_with": raw, "step": 10})
                self.assertEqual((cfg["skip_with"], cfg["step"]), (kept, 10))

    def test_saved_times_run_from_0_01_to_59_59(self):
        for saved, accepted in ((1, True), (3599, True), (0, False), (3600, False)):
            with self.subTest(saved=saved):
                s = app.clean_config({"types": {TABATA: {"work": saved, "rest": saved}}})
                times = s["types"][TABATA]["work"], s["types"][TABATA]["rest"]
                self.assertEqual(times, (saved, saved) if accepted else (20, 10))

    def test_a_time_below_the_step_loads_unchanged(self):
        cfg = app.clean_config({"step": 5, "types": {TABATA: {"work": 3}}})
        self.assertEqual(cfg["types"][TABATA]["work"], 3)

    def test_work_and_rest_bounds_and_types(self):
        defaults = app.default_config()["types"]
        cases = [(0, None), (1, 1), (2, 2), (3, 3), (3595, 3595), (3599, 3599),
                 (3600, None), (-1, None), (True, None), (False, None), (1.0, None),
                 (20.0, None), (3599.0, None), ("20", None), (None, None), ([20], None),
                 (2 ** 63, None)]
        for kind in app.TYPES:
            for key in TIME_FIELDS:
                other = "rest" if key == "work" else "work"
                for raw, want in cases:
                    with self.subTest(kind=kind, key=key, raw=raw):
                        cfg = app.clean_config({"types": {kind: {key: raw, other: 7,
                                                                 "rounds": 3}}})
                        got = cfg["types"][kind]
                        self.assertEqual(got[key], defaults[kind][key] if want is None else want)
                        self.assertIs(type(got[key]), int)
                        self.assertEqual((got[other], got["rounds"]), (7, 3))   # one value at a time

    def test_the_limits_are_the_spec_s(self):
        self.assertEqual((app.TIME_MIN, app.TIME_MAX), (1, 59 * 60 + 59))

class StepTest(unittest.TestCase):
    def seconds(self, start, delta, step):
        return app.fmt_time(app.step_seconds(secs(start), delta, step))

    def minutes(self, start, delta, step):
        return app.fmt_time(app.step_minutes(secs(start), delta, step))

    def test_seconds_move_by_the_time_step_and_wrap_within_the_minute(self):
        for step, up in ((1, ["1:01", "1:02"]), (5, ["1:05", "1:10"]),
                         (10, ["1:10", "1:20"]), (15, ["1:15", "1:30"])):
            with self.subTest(step=step):
                self.assertEqual([self.seconds("1:00", d, step) for d in (1, 2)], up)
                top = "1:%02d" % (60 - step)
                self.assertEqual(self.seconds("1:00", -1, step), top)     # wraps down
                self.assertEqual(self.seconds(top, 1, step), "1:00")      # and up
                self.assertEqual(self.seconds("1:00", 60 // step, step), "1:00")
                self.assertEqual(self.seconds("1:00", -60 // step, step), "1:00")

    def test_at_0_minutes_the_seconds_wrap_between_the_step_and_the_top(self):
        for step in app.STEPS:
            with self.subTest(step=step):
                low, top = "0:%02d" % step, "0:%02d" % (60 - step)
                self.assertEqual(self.seconds(low, -1, step), top)
                self.assertEqual(self.seconds(top, 1, step), low)
                cycle = 60 // step - 1                  # 0:00 is left out
                self.assertEqual(self.seconds(low, cycle, step), low)
                self.assertEqual(self.seconds(low, -cycle, step), low)

    def test_the_spec_examples(self):
        self.assertEqual(self.seconds("1:00", -1, 5), "1:55")
        self.assertEqual(self.seconds("0:05", -1, 5), "0:55")
        self.assertEqual(self.seconds("1:55", 1, 5), "1:00")
        self.assertEqual(self.seconds("1:50", 2, 5), "1:00")
        self.assertEqual(self.minutes("1:00", -1, 5), "0:05")

    def test_seconds_off_the_step_snap_to_it(self):
        self.assertEqual(self.seconds("0:03", 1, 5), "0:05")     # below the step:
        self.assertEqual(self.seconds("0:03", -1, 5), "0:05")    # up to it either way
        self.assertEqual(self.seconds("0:01", -1, 15), "0:15")
        self.assertEqual(self.seconds("1:03", 1, 5), "1:05")
        self.assertEqual(self.seconds("1:03", -1, 5), "1:00")
        self.assertEqual(self.seconds("2:27", 1, 10), "2:30")
        self.assertEqual(self.seconds("2:27", -1, 10), "2:20")
        self.assertEqual(self.seconds("2:50", 1, 15), "2:00")    # past the top: wraps
        self.assertEqual(self.seconds("2:50", -1, 15), "2:45")

    def test_the_highest_time(self):
        self.assertEqual(self.seconds("59:58", 1, 1), "59:59")
        self.assertEqual(self.seconds("59:59", 1, 1), "59:00")
        self.assertEqual(self.minutes("58:59", 1, 1), "59:59")
        for step in (5, 10, 15):
            self.assertEqual(self.seconds("59:00", -1, step), "59:%02d" % (60 - step))

    def test_minutes_move_by_one_and_keep_the_seconds(self):
        self.assertEqual(self.minutes("0:20", 1, 5), "1:20")
        self.assertEqual(self.minutes("1:20", 3, 5), "4:20")
        self.assertEqual(self.minutes("4:20", -1, 5), "3:20")
        self.assertEqual(self.minutes("2:03", -1, 5), "1:03")    # seconds untouched
        self.assertEqual(self.minutes("0:03", 1, 5), "1:03")

    def test_minutes_wrap_between_0_and_59(self):
        self.assertEqual(self.minutes("59:30", 1, 5), "0:30")
        self.assertEqual(self.minutes("0:30", -1, 5), "59:30")
        self.assertEqual(self.minutes("58:30", 3, 5), "1:30")
        self.assertEqual(self.minutes("2:30", -5, 5), "57:30")
        self.assertEqual(self.minutes("0:30", 60, 5), "0:30")
        self.assertEqual(self.minutes("0:30", -60, 5), "0:30")

    def test_minutes_down_past_0_keep_the_seconds(self):
        for step in app.STEPS:
            with self.subTest(step=step):
                self.assertEqual(self.minutes("0:03", -1, step), "59:03")
                self.assertEqual(self.minutes("0:%02d" % step, -1, step), "59:%02d" % step)
                self.assertEqual(self.minutes("0:50", -2, step), "58:50")

    def test_minutes_landing_on_0_keep_the_lowest_time(self):
        for step in app.STEPS:
            with self.subTest(step=step):
                low = "0:%02d" % step
                self.assertEqual(self.minutes("1:00", -1, step), low)
                self.assertEqual(self.minutes("3:00", -3, step), low)
                self.assertEqual(self.minutes("59:00", 1, step), low)
                self.assertEqual(self.minutes("57:00", 3, step), low)
                self.assertEqual(self.minutes("1:30", -1, step), "0:30")
                self.assertEqual(self.minutes("59:30", 1, step), "0:30")
        self.assertEqual(self.minutes("1:03", -1, 5), "0:05")
        self.assertEqual(self.minutes("59:03", 1, 5), "0:05")
        self.assertEqual(self.minutes("0:03", 60, 5), "0:05")     # a full lap lands on 0 too
        self.assertEqual(self.minutes("0:03", -60, 5), "0:05")

    def test_a_burst_of_minutes_keeps_the_lowest_time_at_every_0_it_passes(self):
        self.assertEqual(self.minutes("58:03", 3, 5), "1:05")
        self.assertEqual(self.minutes("2:03", -3, 5), "59:05")
        self.assertEqual(self.minutes("3:00", -9, 15), "54:15")

    def test_rounds_wrap_through_unlimited(self):
        self.assertEqual(app.step_rounds(1, -1), None)
        self.assertEqual(app.step_rounds(None, -1), 99)
        self.assertEqual(app.step_rounds(99, 1), None)
        self.assertEqual(app.step_rounds(None, 1), 1)
        self.assertEqual(app.step_rounds(8, 3), 11)


class ConfigFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "config.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_and_corrupt_files_give_defaults(self):
        self.assertEqual(app.load_config(self.path), app.default_config())
        with open(self.path, "w") as fh:
            fh.write('{"last_type": "fix_')
        self.assertEqual(app.load_config(self.path), app.default_config())

    def test_round_trip(self):
        cfg = app.default_config()
        cfg["types"][FIX_REST]["rounds"] = None
        cfg["sound"] = False
        cfg["skip_with"] = "start"
        app.save_config(cfg, self.path)
        self.assertEqual(app.load_config(self.path), cfg)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_a_file_saved_before_skip_with_loads_with_ok(self):
        old = app.default_config()
        del old["skip_with"]
        old["step"] = 15
        with open(self.path, "w") as fh:
            json.dump(old, fh)
        cfg = app.load_config(self.path)
        self.assertEqual((cfg["skip_with"], cfg["step"]), ("ok", 15))

    def assert_failed_save_leaves_old_file(self, failing_name, failure):
        old = app.default_config()
        app.save_config(old, self.path)
        new = app.default_config()
        new["sound"] = False
        logged = []
        with mock.patch(failing_name, side_effect=failure):
            saved = app.save_config(new, self.path, log=logged.append)
        self.assertEqual((saved, len(logged)), (False, 1))
        self.assertEqual(app.load_config(self.path), old)
        self.assertEqual(os.listdir(self.dir.name), ["config.json"])

    def test_failed_replace_leaves_old_file_and_no_temp_file(self):
        self.assert_failed_save_leaves_old_file("app.os.replace", OSError("busy"))

    def test_failed_write_leaves_old_file_and_no_temp_file(self):
        def write_half_then_fail(cfg, fh, **kwargs):
            fh.write('{"last_type": ')
            raise OSError("disk full")
        self.assert_failed_save_leaves_old_file("app.json.dump", write_half_then_fail)

    def test_failed_fsync_leaves_old_file_and_no_temp_file(self):
        self.assert_failed_save_leaves_old_file("app.os.fsync", OSError("EIO"))

    def test_whole_temp_file_is_synced_before_the_rename(self):
        calls = []
        real_fsync, real_replace = os.fsync, os.replace

        def fsync(fd):
            st = os.fstat(fd)
            calls.append(("fsync", st.st_ino, st.st_size))
            return real_fsync(fd)

        def replace(src, dst):
            calls.append(("replace", os.stat(src).st_ino, None))
            return real_replace(src, dst)

        with mock.patch("app.os.fsync", side_effect=fsync), \
                mock.patch("app.os.replace", side_effect=replace):
            self.assertTrue(app.save_config(app.default_config(), self.path))
        self.assertEqual([c[0] for c in calls], ["fsync", "replace"])
        self.assertEqual(calls[0][1], calls[1][1])                  # the same file,
        self.assertEqual(calls[0][2], os.path.getsize(self.path))   # all of it

    def test_temp_file_left_by_a_crash_is_overwritten(self):
        with open(self.path + ".tmp", "w") as fh:
            fh.write('{"junk": "' + "x" * 5000)    # longer than a config, cut off
        cfg = app.default_config()
        cfg["sound"] = False
        self.assertTrue(app.save_config(cfg, self.path))
        self.assertEqual(os.listdir(self.dir.name), ["config.json"])
        self.assertEqual(app.load_config(self.path), cfg)


def settings_in(folder):
    return os.path.join(folder, "workout-timer", "config.json")


class LegacyConfigTest(unittest.TestCase):
    """Settings saved next to app.py by earlier versions: read until the first
    save at the new place, which removes them."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.legacy = os.path.join(self.dir.name, "app", "config.json")
        self.path = settings_in(os.path.join(self.dir.name, "user"))
        os.makedirs(os.path.dirname(self.legacy))
        self.old = app.default_config()
        self.old.update(sound=False, last_type=FIX_WORK)
        with open(self.legacy, "w") as fh:
            json.dump(self.old, fh)
        with open(self.legacy) as fh:
            self.legacy_text = fh.read()
        self.logged = []

    def tearDown(self):
        self.dir.cleanup()

    def open_settings(self):
        return app.open_settings(self.path, self.legacy, log=self.logged.append)

    def assert_legacy_untouched(self):
        with open(self.legacy) as fh:
            self.assertEqual(fh.read(), self.legacy_text)

    def test_a_failed_removal_is_harmless(self):
        cfg, save = self.open_settings()
        cfg["step"] = 10
        with mock.patch("app.os.remove", side_effect=OSError("read-only")) as remove:
            self.assertTrue(save(cfg))
            self.assertTrue(save(cfg))
        self.assertEqual(remove.call_count, 1)     # tried once, not on every save
        self.assert_legacy_untouched()
        self.assertEqual(app.load_config(self.path), cfg)
        self.assertEqual(self.open_settings()[0], cfg)    # the new file, not the old one


if __name__ == "__main__":
    unittest.main()
