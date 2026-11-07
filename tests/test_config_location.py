"""Where the settings file lives (config_path), reading the old
config.json next to app.py until the first save, save_config into missing or
unwritable folders, what --help lists, and main()'s wiring.

Nothing here may touch the real ~/.config or the repo's config.json: every
test works in a temp dir with HOME and the settings variables patched, and
support.py's audit hook blocks and reports any access to either."""
import contextlib
import copy
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import tearDownModule  # noqa: E402,F401  (first: guards the real settings)
import app  # noqa: E402
import support  # noqa: E402
from app import FIX_REST, FIX_WORK, TABATA  # noqa: E402

APP_PY = os.path.join(support.REPO, "app.py")
TAIL = os.path.join("workout-timer", "config.json")
SETTINGS_VARS = ("WORKOUT_TIMER_CONFIG", "XDG_CONFIG_HOME", "APPDATA")
IS_ROOT = getattr(os, "geteuid", lambda: 1)() == 0
NO_CHMOD = IS_ROOT or os.name == "nt"

def tree(root):
    """Every file and folder under root, relative, sorted."""
    out = []
    for folder, dirs, files in os.walk(root):
        for name in dirs + files:
            out.append(os.path.relpath(os.path.join(folder, name), root))
    return sorted(out)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


@contextlib.contextmanager
def isolated_env(home, **env):
    """os.environ with HOME and USERPROFILE at `home`, no settings variables,
    plus `env`."""
    with mock.patch.dict(os.environ):
        for name in SETTINGS_VARS:
            os.environ.pop(name, None)
        os.environ["HOME"] = home
        os.environ["USERPROFILE"] = home     # ntpath.expanduser reads it on Windows
        os.environ.update(env)
        yield


def custom_cfg():
    cfg = app.default_config()
    cfg.update(last_type=FIX_WORK, get_ready=10, sound=False, step=15, skip_with="start")
    cfg["types"][TABATA].update(work=40, rest=20, rounds=None)
    cfg["types"][FIX_WORK].update(work=120, rounds=12)
    return cfg


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def unlock_on_cleanup(self, path):
        self.addCleanup(lambda: os.path.isdir(path) and os.chmod(path, 0o755))


# --- 1. config_path ------------------------------------------------------------

class ConfigPathTest(unittest.TestCase):
    HOME = os.path.abspath(os.path.join(os.sep, "qa", "home"))
    XDG = os.path.abspath(os.path.join(os.sep, "qa", "xdg"))
    APPDATA = os.path.abspath(os.path.join(os.sep, "qa", "roaming"))

    def where(self, windows, **env):
        return app.config_path(env=env, windows=windows, home=self.HOME)

    def test_env_var_wins_over_xdg_appdata_and_home(self):
        for windows in (False, True):
            for custom in ("/qa/elsewhere/wt.json", "wt.json", "/qa/no-extension"):
                with self.subTest(windows=windows, custom=custom):
                    got = self.where(windows, WORKOUT_TIMER_CONFIG=custom,
                                     XDG_CONFIG_HOME=self.XDG, APPDATA=self.APPDATA)
                    self.assertEqual(got, os.path.abspath(custom))   # nothing appended

    def test_empty_env_var_is_ignored(self):
        self.assertEqual(self.where(False, WORKOUT_TIMER_CONFIG=""),
                         os.path.join(self.HOME, ".config", TAIL))
        self.assertEqual(self.where(False, WORKOUT_TIMER_CONFIG="", XDG_CONFIG_HOME=self.XDG),
                         os.path.join(self.XDG, TAIL))
        self.assertEqual(self.where(True, WORKOUT_TIMER_CONFIG="", APPDATA=self.APPDATA),
                         os.path.join(self.APPDATA, TAIL))

    def test_windows_with_appdata_ignores_xdg(self):
        self.assertEqual(self.where(True, APPDATA=self.APPDATA, XDG_CONFIG_HOME=self.XDG),
                         os.path.join(self.APPDATA, TAIL))

    def test_windows_without_appdata_falls_back_to_roaming_under_home(self):
        roaming = os.path.join(self.HOME, "AppData", "Roaming", TAIL)
        self.assertEqual(self.where(True), roaming)
        self.assertEqual(self.where(True, APPDATA=""), roaming)
        self.assertEqual(self.where(True, XDG_CONFIG_HOME=self.XDG), roaming)
        self.assertEqual(self.where(True, APPDATA="", XDG_CONFIG_HOME=self.XDG), roaming)

    def test_xdg_absolute_is_used_and_appdata_ignored(self):
        self.assertEqual(self.where(False, XDG_CONFIG_HOME=self.XDG, APPDATA=self.APPDATA),
                         os.path.join(self.XDG, TAIL))

    def test_xdg_relative_or_empty_falls_back_to_dot_config(self):
        for xdg in ("relative", "rel/config", ".config", "./cfg", "~/.config", ""):
            with self.subTest(xdg=xdg):
                self.assertEqual(self.where(False, XDG_CONFIG_HOME=xdg),
                                 os.path.join(self.HOME, ".config", TAIL))

    def test_default_is_dot_config_under_home(self):
        self.assertEqual(self.where(False), os.path.join(self.HOME, ".config", TAIL))
        self.assertEqual(self.where(False, APPDATA=self.APPDATA),     # not Windows: ignored
                         os.path.join(self.HOME, ".config", TAIL))

    def test_every_derived_path_ends_in_workout_timer_config_json(self):
        cases = [(False, {}), (False, {"XDG_CONFIG_HOME": self.XDG}),
                 (False, {"XDG_CONFIG_HOME": "rel"}), (True, {}),
                 (True, {"APPDATA": self.APPDATA})]
        for windows, env in cases:
            with self.subTest(windows=windows, env=env):
                got = self.where(windows, **env)
                self.assertTrue(got.endswith(os.sep + TAIL), got)
                self.assertTrue(os.path.isabs(got), got)

    def test_called_without_arguments_it_reads_the_live_environment(self):
        # main() calls config_path() bare: it must see os.environ as it is
        # at run time (HOME included), not as it was at import.
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            with isolated_env(home):
                self.assertEqual(app.config_path(), os.path.join(home, ".config", TAIL))
            xdg = os.path.join(tmp, "xdg")
            with isolated_env(home, XDG_CONFIG_HOME=xdg):
                self.assertEqual(app.config_path(), os.path.join(xdg, TAIL))
            custom = os.path.join(tmp, "x", "wt.json")
            with isolated_env(home, WORKOUT_TIMER_CONFIG=custom, XDG_CONFIG_HOME=xdg):
                self.assertEqual(app.config_path(), custom)

    def test_computing_the_path_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with isolated_env(os.path.join(tmp, "home")):
                app.config_path()
            self.assertEqual(tree(tmp), [])


class GuardSelfTest(unittest.TestCase):
    """The audit hook really stops access to the real settings (checked with
    reads only, so a broken hook can't do harm)."""

    def test_reading_the_real_files_is_blocked(self):
        paths = sorted(support.REAL_FILES) + [os.path.join(folder, "config.json")
                                              for folder in sorted(support.REAL_DIRS)]
        self.assertIn(app.LEGACY_CONFIG_PATH, paths)
        before = len(support.touched)
        for path in paths:
            with self.subTest(path=path):
                with self.assertRaises(RuntimeError):
                    open(path, "rb")
        self.assertEqual(len(support.touched) - before, len(paths))
        del support.touched[before:]               # these were on purpose


class EnvValueTest(TempDirTest):
    """$WORKOUT_TIMER_CONFIG with ~ or a relative path."""

    def test_tilde_is_expanded_with_the_live_home(self):
        home = os.path.join(self.tmp, "home")
        with isolated_env(home):
            self.assertEqual(app.config_path(env={"WORKOUT_TIMER_CONFIG": "~/wt.json"}),
                             os.path.join(home, "wt.json"))
            with isolated_env(home, WORKOUT_TIMER_CONFIG="~/a/b/wt.json"):
                self.assertEqual(app.config_path(), os.path.join(home, "a", "b", "wt.json"))

    def test_relative_is_made_absolute_from_the_working_folder(self):
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.tmp)
        got = app.config_path(env={"WORKOUT_TIMER_CONFIG": os.path.join("rel", "wt.json")})
        self.assertEqual(got, os.path.join(self.tmp, "rel", "wt.json"))
        os.chdir(os.path.dirname(self.tmp))
        self.assertTrue(os.path.isabs(got))                  # fixed once, not re-resolved

    def test_only_tilde_names_the_home_folder_and_fails_cleanly(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home)
        with isolated_env(home):
            path = app.config_path(env={"WORKOUT_TIMER_CONFIG": "~"})
        self.assertEqual(path, home)
        logged = []
        cfg, save = app.open_settings(path, None, log=logged.append)
        self.assertEqual(cfg, app.default_config())
        self.assertFalse(save(custom_cfg()))
        self.assertTrue(os.path.isdir(home))
        self.assertEqual(len(logged), 1)

    def test_legacy_config_path_follows_the_env_var(self):
        self.assertIsNone(app.legacy_config_path({"WORKOUT_TIMER_CONFIG": "~/wt.json"}))
        self.assertIsNone(app.legacy_config_path({"WORKOUT_TIMER_CONFIG": "rel.json"}))
        self.assertEqual(app.legacy_config_path({"WORKOUT_TIMER_CONFIG": ""}),
                         app.LEGACY_CONFIG_PATH)
        self.assertEqual(app.legacy_config_path({"XDG_CONFIG_HOME": "/x"}), app.LEGACY_CONFIG_PATH)
        self.assertEqual(app.legacy_config_path({}), app.LEGACY_CONFIG_PATH)
        with mock.patch.dict(os.environ, {"WORKOUT_TIMER_CONFIG": "/qa/wt.json"}):
            self.assertIsNone(app.legacy_config_path())     # bare, as main() calls it


# --- 2. reading the old config.json until the first save -------------------------

class LegacyMigrationTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.legacy = os.path.join(self.tmp, "appdir", "config.json")
        self.new = os.path.join(self.tmp, "home", ".config", TAIL)
        self.old_cfg = custom_cfg()
        write_json(self.legacy, self.old_cfg)

    def load(self):
        return app.open_settings(self.new, self.legacy)[0]

    def test_only_legacy_exists_its_values_load(self):
        self.assertEqual(self.load(), self.old_cfg)

    def test_loading_from_legacy_writes_nothing(self):
        before = read_bytes(self.legacy)
        self.load()
        self.assertFalse(os.path.exists(os.path.dirname(self.new)))
        self.assertEqual(read_bytes(self.legacy), before)

    def test_both_exist_the_new_one_wins(self):
        newer = app.default_config()
        newer.update(last_type=FIX_REST, step=1)
        write_json(self.new, newer)
        self.assertEqual(self.load(), newer)

    def test_save_writes_the_new_place_and_removes_legacy(self):
        logged = []
        cfg, save = app.open_settings(self.new, self.legacy, log=logged.append)
        self.assertEqual(cfg, self.old_cfg)
        cfg["types"][FIX_REST]["rest"] = 60
        self.assertTrue(save(cfg))
        self.assertEqual(logged, ["workout-timer: settings moved to " + self.new])
        self.assertTrue(os.path.isfile(self.new))
        self.assertEqual(self.load(), cfg)
        self.assertEqual(app.load_config(self.new), cfg)        # without the fallback too
        self.assertEqual(os.listdir(os.path.dirname(self.legacy)), [])
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.new))), ["config.json"])

    def test_after_the_first_save_legacy_edits_are_ignored(self):
        app.save_config(app.default_config(), self.new)
        write_json(self.legacy, custom_cfg())
        self.assertEqual(self.load(), app.default_config())

    def test_corrupt_new_file_gives_defaults_not_legacy(self):
        # Legacy is read only while the new file doesn't exist yet.
        for junk in ('{"sound": ', "", "[]", "null", "not json at all"):
            with self.subTest(junk=junk):
                os.makedirs(os.path.dirname(self.new), exist_ok=True)
                with open(self.new, "w") as fh:
                    fh.write(junk)
                self.assertEqual(self.load(), app.default_config())

    def test_one_bad_value_in_new_file_falls_back_to_default_not_legacy(self):
        newer = app.default_config()
        newer.update(last_type=FIX_REST, sound="loud")        # sound invalid
        write_json(self.new, newer)
        cfg = self.load()
        self.assertEqual(cfg["last_type"], FIX_REST)          # from the new file
        self.assertIs(cfg["sound"], True)                     # default, not legacy's False
        self.assertEqual(cfg["step"], app.default_config()["step"])

    def test_new_path_is_a_folder_gives_defaults_without_raising(self):
        os.makedirs(self.new)
        self.assertEqual(self.load(), app.default_config())

    def test_corrupt_legacy_and_no_new_file_gives_defaults(self):
        with open(self.legacy, "w") as fh:
            fh.write("{{{")
        self.assertEqual(self.load(), app.default_config())

    def test_legacy_with_one_bad_value_keeps_the_rest(self):
        raw = custom_cfg()
        raw["step"] = 7
        write_json(self.legacy, raw)
        cfg = self.load()
        self.assertEqual(cfg["step"], app.default_config()["step"])
        self.assertEqual(cfg["types"][FIX_WORK], custom_cfg()["types"][FIX_WORK])

    def test_neither_file_or_no_legacy_path_gives_defaults(self):
        os.remove(self.legacy)
        self.assertEqual(self.load(), app.default_config())
        self.assertEqual(app.load_config(self.new), app.default_config())
        self.assertEqual(app.open_settings(self.new, None)[0], app.default_config())


class OpenSettingsMoveTest(TempDirTest):
    """open_settings(): the old file goes only after a save at the new place
    succeeds, and only if the settings came from it."""

    def setUp(self):
        super().setUp()
        self.legacy = os.path.join(self.tmp, "appdir", "config.json")
        self.new = os.path.join(self.tmp, "home", ".config", TAIL)
        write_json(self.legacy, custom_cfg())
        self.legacy_bytes = read_bytes(self.legacy)
        self.logged = []

    def open(self):
        return app.open_settings(self.new, self.legacy, log=self.logged.append)

    def moved_logs(self):
        return [line for line in self.logged if "settings moved to" in line]

    def assert_legacy_intact(self):
        self.assertEqual(read_bytes(self.legacy), self.legacy_bytes)

    def test_opening_alone_moves_nothing(self):
        cfg, _ = self.open()
        self.assertEqual(cfg, custom_cfg())
        cfg2, _ = self.open()                       # and again: still read from the old file
        self.assertEqual(cfg2, custom_cfg())
        self.assert_legacy_intact()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "home")))
        self.assertEqual(self.logged, [])

    def test_a_failed_save_moves_nothing_then_the_first_success_does(self):
        blocker = os.path.join(self.tmp, "home")
        open(blocker, "w").close()                  # ~/.config can't be made
        cfg, save = self.open()
        cfg["step"] = 1
        self.assertFalse(save(cfg))
        self.assertFalse(save(cfg))
        self.assert_legacy_intact()
        self.assertEqual(self.moved_logs(), [])
        self.assertEqual(len([l for l in self.logged if "cannot save" in l]), 2)
        os.remove(blocker)
        self.assertTrue(save(cfg))
        self.assertFalse(os.path.exists(self.legacy))
        self.assertEqual(self.moved_logs(), ["workout-timer: settings moved to " + self.new])
        self.assertEqual(app.load_config(self.new), cfg)

    def test_a_save_failing_at_the_rename_moves_nothing(self):
        cfg, save = self.open()
        with mock.patch.object(app.os, "replace", side_effect=OSError("disk full")):
            self.assertFalse(save(cfg))
        self.assert_legacy_intact()
        self.assertEqual(self.moved_logs(), [])
        self.assertFalse(os.path.exists(self.new))

    def test_the_move_is_logged_once(self):
        cfg, save = self.open()
        for step in (1, 10, 15, 5):
            cfg["step"] = step
            self.assertTrue(save(cfg))
        self.assertEqual(len(self.moved_logs()), 1)
        self.assertEqual(self.logged, self.moved_logs())    # nothing else logged
        self.assertEqual(app.load_config(self.new)["step"], 5)

    def test_a_failed_save_after_the_move_logs_no_second_move(self):
        cfg, save = self.open()
        self.assertTrue(save(cfg))
        os.remove(self.new)
        os.rmdir(os.path.dirname(self.new))
        open(os.path.dirname(self.new), "w").close()      # folder replaced by a file
        self.assertFalse(save(cfg))
        os.remove(os.path.dirname(self.new))
        self.assertTrue(save(cfg))
        self.assertEqual(len(self.moved_logs()), 1)

    def test_not_moved_when_the_new_file_existed_at_open(self):
        write_json(self.new, app.default_config())
        cfg, save = self.open()
        self.assertEqual(cfg, app.default_config())
        for _ in range(3):
            self.assertTrue(save(cfg))
        self.assert_legacy_intact()
        self.assertEqual(self.logged, [])

    def test_not_moved_when_the_new_file_exists_but_is_corrupt(self):
        os.makedirs(os.path.dirname(self.new))
        with open(self.new, "w") as fh:
            fh.write("{{{")
        cfg, save = self.open()
        self.assertEqual(cfg, app.default_config())
        self.assertTrue(save(cfg))
        self.assert_legacy_intact()

    def test_no_legacy_path_moves_nothing(self):
        cfg, save = app.open_settings(self.new, None, log=self.logged.append)
        self.assertEqual(cfg, app.default_config())
        self.assertTrue(save(cfg))
        self.assert_legacy_intact()
        self.assertEqual(self.logged, [])

    def test_a_corrupt_old_file_gives_defaults_and_is_removed_by_the_first_save(self):
        # What the code does: a corrupt old file still counts as "the settings
        # came from it" (it was the file consulted), so it goes with the first
        # save. The first save that succeeds writes the new file and deletes
        # the old one.
        for junk in ("{{{", "", "[]"):
            with self.subTest(junk=junk):
                if os.path.exists(self.new):
                    os.remove(self.new)
                with open(self.legacy, "w") as fh:
                    fh.write(junk)
                self.logged.clear()
                cfg, save = self.open()
                self.assertEqual(cfg, app.default_config())
                self.assertTrue(os.path.exists(self.legacy))     # not on load
                self.assertTrue(save(cfg))
                self.assertFalse(os.path.exists(self.legacy))
                self.assertEqual(len(self.moved_logs()), 1)

    def test_old_file_with_one_bad_value_loads_the_rest_and_is_moved(self):
        raw = custom_cfg()
        raw["step"] = 7
        write_json(self.legacy, raw)
        cfg, save = self.open()
        self.assertEqual(cfg["types"], custom_cfg()["types"])
        self.assertTrue(save(cfg))
        self.assertFalse(os.path.exists(self.legacy))
        self.assertEqual(app.load_config(self.new), cfg)

    def test_old_path_is_a_folder_save_still_works(self):
        os.remove(self.legacy)
        os.makedirs(os.path.join(self.legacy, "inside"))
        cfg, save = self.open()
        self.assertEqual(cfg, app.default_config())
        self.assertTrue(save(cfg))                          # removal fails, ignored
        self.assertTrue(os.path.isdir(os.path.join(self.legacy, "inside")))

    def test_old_file_already_gone_at_save_is_harmless(self):
        cfg, save = self.open()
        os.remove(self.legacy)                              # e.g. another instance moved it
        self.assertTrue(save(cfg))
        self.assertEqual(app.load_config(self.new), cfg)

    def test_reset_by_deleting_the_new_file_gives_defaults_after_a_move(self):
        cfg, save = self.open()
        save(cfg)
        os.remove(self.new)
        self.assertEqual(self.open()[0], app.default_config())

    def test_open_settings_never_writes_on_its_own(self):
        before = {p: read_bytes(os.path.join(self.tmp, p)) for p in tree(self.tmp)
                  if os.path.isfile(os.path.join(self.tmp, p))}
        self.open()
        after = {p: read_bytes(os.path.join(self.tmp, p)) for p in tree(self.tmp)
                 if os.path.isfile(os.path.join(self.tmp, p))}
        self.assertEqual(after, before)


# --- 3. save_config: missing and unwritable folders ------------------------------

class SaveConfigTest(TempDirTest):
    def save(self, path, cfg=None):
        logged = []
        ok = app.save_config(cfg or custom_cfg(), path, log=logged.append)
        return ok, logged

    def assert_no_tmp_anywhere(self):
        leftovers = [p for p in tree(self.tmp) if p.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_missing_nested_folders_are_created(self):
        path = os.path.join(self.tmp, "a", "b", "c", TAIL)
        ok, logged = self.save(path)
        self.assertEqual((ok, logged), (True, []))
        self.assertEqual(app.load_config(path), custom_cfg())
        self.assertEqual(os.listdir(os.path.dirname(path)), ["config.json"])

    def test_saving_twice_overwrites_and_leaves_no_tmp(self):
        path = os.path.join(self.tmp, TAIL)
        self.save(path, app.default_config())
        ok, _ = self.save(path)
        self.assertTrue(ok)
        self.assertEqual(app.load_config(path), custom_cfg())
        self.assert_no_tmp_anywhere()

    def test_parent_is_a_file(self):
        blocker = os.path.join(self.tmp, "blocker")
        with open(blocker, "w") as fh:
            fh.write("x")
        for path in (os.path.join(blocker, "config.json"),
                     os.path.join(blocker, "deeper", TAIL)):
            with self.subTest(path=path):
                ok, logged = self.save(path)
                self.assertFalse(ok)
                self.assertEqual(len(logged), 1)
                self.assertIn("cannot save settings", logged[0])
                self.assertIn(path, logged[0])
                self.assertEqual(read_bytes(blocker), b"x")
                self.assert_no_tmp_anywhere()

    def test_path_is_a_folder(self):
        path = os.path.join(self.tmp, "wt.json")
        os.makedirs(os.path.join(path, "inside"))
        ok, logged = self.save(path)
        self.assertEqual((ok, len(logged)), (False, 1))
        self.assertTrue(os.path.isdir(os.path.join(path, "inside")))
        self.assert_no_tmp_anywhere()

    @unittest.skipIf(NO_CHMOD, "needs POSIX permissions and a non-root user")
    def test_read_only_existing_folder_keeps_the_old_file(self):
        folder = os.path.join(self.tmp, "workout-timer")
        path = os.path.join(folder, "config.json")
        self.save(path, app.default_config())
        before = read_bytes(path)
        os.chmod(folder, 0o500)
        self.unlock_on_cleanup(folder)
        ok, logged = self.save(path)
        os.chmod(folder, 0o755)
        self.assertEqual((ok, len(logged)), (False, 1))
        self.assertEqual(read_bytes(path), before)
        self.assertEqual(os.listdir(folder), ["config.json"])

    @unittest.skipIf(NO_CHMOD, "needs POSIX permissions and a non-root user")
    def test_folder_that_cannot_be_created(self):
        locked = os.path.join(self.tmp, "locked")
        os.makedirs(locked)
        os.chmod(locked, 0o500)
        self.unlock_on_cleanup(locked)
        ok, logged = self.save(os.path.join(locked, "cfg", TAIL))
        os.chmod(locked, 0o755)
        self.assertEqual((ok, len(logged)), (False, 1))
        self.assertEqual(os.listdir(locked), [])

    @unittest.skipIf(NO_CHMOD, "needs POSIX permissions and a non-root user")
    def test_a_later_retry_succeeds_once_writable(self):
        folder = os.path.join(self.tmp, "workout-timer")
        os.makedirs(folder)
        os.chmod(folder, 0o500)
        self.unlock_on_cleanup(folder)
        path = os.path.join(folder, "config.json")
        self.assertFalse(self.save(path)[0])
        os.chmod(folder, 0o755)
        self.assertEqual(self.save(path), (True, []))
        self.assertEqual(app.load_config(path), custom_cfg())

    def test_relative_path_is_relative_to_the_working_folder(self):
        # $WORKOUT_TIMER_CONFIG=wt.json: dirname is "", which makedirs refuses;
        # save_config must still work.
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.tmp)
        self.assertEqual(self.save("wt.json"), (True, []))
        self.assertEqual(self.save(os.path.join("sub", "wt.json")), (True, []))
        self.assertEqual(tree(self.tmp), ["sub", os.path.join("sub", "wt.json"), "wt.json"])

    def test_failure_never_raises_with_the_default_logger(self):
        blocker = os.path.join(self.tmp, "blocker")
        open(blocker, "w").close()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertFalse(app.save_config(custom_cfg(), os.path.join(blocker, "c.json")))
        self.assertIn("cannot save settings", out.getvalue())


# --- 4. what --help lists -------------------------------------------------------

# busybar-manager skips these when it turns --help into dashboard controls
# (ARG_SKIP in its server.js); anything else listed becomes a control.
MANAGER_SKIPS = {"-h", "--help", "--host", "--token", "--test"}
OPTION_LINE = re.compile(r"^ {2}(-{1,2}[\w-]+.*?)(?:[ \t]{2,}\S.*)?$")


def listed_options(help_text):
    # Python 3.14 colours help when FORCE_COLOR is set, even into a pipe.
    help_text = re.sub(r"\x1b\[[0-9;]*m", "", help_text)
    names = set()
    for line in help_text.splitlines():
        m = OPTION_LINE.match(line)
        if m:
            names.update(re.findall(r"(?<![\w-])-{1,2}[\w-]+", m.group(1)))
    return names


class HelpTest(unittest.TestCase):
    def test_help_lists_only_what_the_manager_skips(self):
        names = listed_options(app.build_parser().format_help())
        self.assertEqual(names, MANAGER_SKIPS)

    def test_help_as_a_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items()
                   if k not in SETTINGS_VARS + ("FORCE_COLOR", "NO_COLOR", "PYTHON_COLORS")}
            env["HOME"] = tmp
            env["PYTHONDONTWRITEBYTECODE"] = "1"   # macOS's python caches under ~/Library
            r = subprocess.run([sys.executable, APP_PY, "--help"], env=env, cwd=tmp,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stderr, "")
            self.assertNotIn("\x1b[", r.stdout)
            self.assertEqual(listed_options(r.stdout), MANAGER_SKIPS)
            # --help writes no settings (the interpreter itself may cache
            # bytecode under HOME, which isn't the app's doing).
            self.assertEqual([p for p in tree(tmp) if "workout-timer" in p or
                              p.startswith(".config") or p.endswith(".json")], [])


# --- 5/6. main() wiring ----------------------------------------------------------

class StubBar:
    on_screen = True

    def __init__(self, host, token=None):
        self.base = host

    def draw(self, elements):
        return True

    def play(self, sound):
        pass

    def install_sounds(self):
        return True

    def clear(self):
        pass


class MainWiringTest(TempDirTest):
    """main() with a stub bar and a listener that hands over one batch of
    events and then stops the app (as Ctrl-C would)."""

    def setUp(self):
        super().setUp()
        self.home = os.path.join(self.tmp, "home")
        self.legacy = os.path.join(self.tmp, "appdir", "config.json")

    def run_main(self, argv, events, env=None, on_stop=None):
        seen = {}

        class Listener:
            def __init__(self, host, token=None):
                self.events = list(events)

            start = stop = lambda self: None

            def poll(self):
                batch, self.events = self.events, []
                return batch

            def wait(self, timeout):
                if not self.events:
                    if on_stop:
                        on_stop()
                    raise KeyboardInterrupt

        class Ctrl(app.Controller):
            def __init__(self, cfg):
                seen["initial"] = copy.deepcopy(cfg)
                super().__init__(cfg)
                seen["ctrl"] = self

        out = io.StringIO()
        with isolated_env(self.home, **(env or {})), \
                mock.patch.object(app, "LEGACY_CONFIG_PATH", self.legacy), \
                mock.patch.object(app, "Bar", StubBar), \
                mock.patch.object(app, "InputListener", Listener), \
                mock.patch.object(app, "Controller", Ctrl), \
                mock.patch.object(app.signal, "signal"), \
                contextlib.redirect_stdout(out):
            status = app.main(["--host", "stub"] + argv)
        seen["status"], seen["out"] = status, out.getvalue()
        return seen

    PICK_FIXED_REST = [app.Wheel(1, 100.0, False), "ok"]      # a change, then a press

    def test_env_var_path_is_the_only_file_written(self):
        custom = os.path.join(self.tmp, "custom", "deep", "wt.json")
        seen = self.run_main([], self.PICK_FIXED_REST, env={"WORKOUT_TIMER_CONFIG": custom})
        self.assertEqual(seen["status"], 0)
        self.assertEqual(app.load_config(custom)["last_type"], FIX_REST)
        self.assertEqual(tree(self.tmp), ["custom", os.path.join("custom", "deep"),
                                          os.path.join("custom", "deep", "wt.json")])

    def test_default_path_under_home(self):
        seen = self.run_main([], self.PICK_FIXED_REST)
        self.assertEqual(seen["status"], 0)
        path = os.path.join(self.home, ".config", TAIL)
        self.assertEqual(app.load_config(path)["last_type"], FIX_REST)
        self.assertEqual([p for p in tree(self.tmp) if os.path.isfile(os.path.join(self.tmp, p))],
                         [os.path.relpath(path, self.tmp)])

    def test_xdg_config_home_path(self):
        xdg = os.path.join(self.tmp, "xdg")
        self.run_main([], self.PICK_FIXED_REST, env={"XDG_CONFIG_HOME": xdg})
        self.assertEqual(app.load_config(os.path.join(xdg, TAIL))["last_type"], FIX_REST)
        self.assertFalse(os.path.exists(self.home))

    def test_legacy_values_load_then_move_to_the_new_place(self):
        write_json(self.legacy, custom_cfg())
        legacy_bytes = read_bytes(self.legacy)
        new = os.path.join(self.home, ".config", TAIL)
        seen = self.run_main([], ["ok"])
        self.assertEqual(seen["initial"], custom_cfg())
        self.assertFalse(os.path.exists(new))                 # nothing changed: nothing saved
        self.assertEqual(read_bytes(self.legacy), legacy_bytes)
        seen = self.run_main([], [app.Wheel(-1, 100.0, False), "ok"])
        saved = app.load_config(new)
        self.assertEqual(saved["last_type"], FIX_REST)        # FIXED WORK, one detent back
        self.assertEqual((saved["sound"], saved["step"]), (False, 15))   # carried over
        self.assertFalse(os.path.exists(self.legacy))
        self.assertEqual(seen["out"].count("settings moved to " + new), 1)

    def test_with_the_env_var_legacy_is_neither_read_nor_removed(self):
        write_json(self.legacy, custom_cfg())
        legacy_bytes = read_bytes(self.legacy)
        custom = os.path.join(self.tmp, "new", "wt.json")
        seen = self.run_main([], self.PICK_FIXED_REST, env={"WORKOUT_TIMER_CONFIG": custom})
        self.assertEqual(seen["initial"], app.default_config())
        self.assertEqual(app.load_config(custom)["last_type"], FIX_REST)
        self.assertEqual(read_bytes(self.legacy), legacy_bytes)
        self.assertFalse(os.path.exists(self.home))

    def test_tilde_env_value_through_main(self):
        self.addCleanup(os.chdir, os.getcwd())
        cwd = os.path.join(self.tmp, "cwd")
        os.makedirs(cwd)
        os.chdir(cwd)
        self.run_main([], self.PICK_FIXED_REST, env={"WORKOUT_TIMER_CONFIG": "~/cfg/wt.json"})
        self.assertEqual(app.load_config(os.path.join(self.home, "cfg", "wt.json"))["last_type"],
                         FIX_REST)
        self.assertEqual(os.listdir(cwd), [])               # no literal "~" folder

    def test_relative_env_value_through_main(self):
        self.addCleanup(os.chdir, os.getcwd())
        cwd = os.path.join(self.tmp, "cwd")
        os.makedirs(cwd)
        os.chdir(cwd)
        self.run_main([], self.PICK_FIXED_REST,
                      env={"WORKOUT_TIMER_CONFIG": os.path.join("rel", "wt.json")})
        self.assertEqual(app.load_config(os.path.join(cwd, "rel", "wt.json"))["last_type"],
                         FIX_REST)

    def test_with_the_env_var_legacy_stays_byte_identical_over_many_saves(self):
        write_json(self.legacy, custom_cfg())
        st = os.stat(self.legacy)
        legacy_bytes = read_bytes(self.legacy)
        custom = os.path.join(self.tmp, "new", "wt.json")
        presses = [app.Wheel(1, 100.0, False), "ok",          # TYPE: FIXED REST, saved
                   "ok", app.Wheel(1, 100.0, False)]          # rest +step, saved on exit
        for _ in range(2):
            seen = self.run_main([], presses, env={"WORKOUT_TIMER_CONFIG": custom})
            self.assertNotIn("settings moved", seen["out"])
        self.assertTrue(os.path.isfile(custom))
        st2 = os.stat(self.legacy)
        self.assertEqual(read_bytes(self.legacy), legacy_bytes)
        self.assertEqual((st2.st_ino, st2.st_mtime_ns), (st.st_ino, st.st_mtime_ns))

    def test_env_var_naming_the_old_file_itself_uses_it_and_keeps_it(self):
        write_json(self.legacy, custom_cfg())
        seen = self.run_main([], [app.Wheel(-1, 100.0, False), "ok"],
                             env={"WORKOUT_TIMER_CONFIG": self.legacy})
        self.assertEqual(seen["initial"], custom_cfg())
        self.assertEqual(app.load_config(self.legacy)["last_type"], FIX_REST)
        self.assertNotIn("settings moved", seen["out"])

    def test_failed_save_keeps_legacy_and_the_retry_on_exit_moves_it(self):
        write_json(self.legacy, custom_cfg())
        os.makedirs(self.home)
        blocker = os.path.join(self.home, ".config")
        open(blocker, "w").close()                            # ~/.config is a file
        seen = self.run_main([], [app.Wheel(-1, 100.0, False), "ok"],
                             on_stop=lambda: (self.assertTrue(os.path.exists(self.legacy)),
                                              os.remove(blocker)))
        self.assertEqual(seen["out"].count("cannot save settings"), 1)
        self.assertEqual(seen["out"].count("settings moved to"), 1)
        self.assertFalse(os.path.exists(self.legacy))
        saved = app.load_config(os.path.join(self.home, ".config", TAIL))
        self.assertEqual((saved["last_type"], saved["step"]), (FIX_REST, 15))

    def test_unchanged_legacy_settings_are_not_moved_on_exit(self):
        write_json(self.legacy, custom_cfg())
        legacy_bytes = read_bytes(self.legacy)
        seen = self.run_main([], ["ok", "back", "ok"])        # moves around, changes nothing
        self.assertEqual(read_bytes(self.legacy), legacy_bytes)
        self.assertNotIn("settings moved", seen["out"])
        self.assertFalse(os.path.exists(self.home))

    def test_a_change_without_a_later_press_is_saved_on_exit(self):
        custom = os.path.join(self.tmp, "wt.json")
        seen = self.run_main([], ["ok", app.Wheel(1, 100.0, False)],   # TYPE ok, WORK +1
                             env={"WORKOUT_TIMER_CONFIG": custom})
        work = seen["ctrl"].cfg["types"][TABATA]["work"]
        self.assertNotEqual(work, 20)
        self.assertEqual(app.load_config(custom)["types"][TABATA]["work"], work)

    def test_unwritable_location_is_reported_and_the_app_carries_on(self):
        blocker = os.path.join(self.tmp, "blocker")
        open(blocker, "w").close()
        custom = os.path.join(blocker, "wt.json")
        seen = self.run_main([], self.PICK_FIXED_REST, env={"WORKOUT_TIMER_CONFIG": custom})
        self.assertEqual(seen["status"], 0)
        self.assertEqual(seen["out"].count("cannot save settings"), 2)   # on the press, on exit
        self.assertEqual(tree(self.tmp), ["blocker"])

    def test_failed_save_is_retried_on_exit_into_a_new_folder(self):
        blocker = os.path.join(self.tmp, "cfg")
        open(blocker, "w").close()
        custom = os.path.join(blocker, "workout-timer", "wt.json")
        seen = self.run_main([], self.PICK_FIXED_REST, env={"WORKOUT_TIMER_CONFIG": custom},
                             on_stop=lambda: os.remove(blocker))
        self.assertEqual(seen["out"].count("cannot save settings"), 1)
        self.assertEqual(app.load_config(custom)["last_type"], FIX_REST)

    def test_test_flag_reads_and_saves_nothing(self):
        write_json(self.legacy, custom_cfg())
        before = tree(self.tmp)
        with mock.patch.object(app, "load_config", side_effect=AssertionError("read")), \
                mock.patch.object(app, "save_config", side_effect=AssertionError("saved")), \
                isolated_env(self.home), \
                mock.patch.object(app, "LEGACY_CONFIG_PATH", self.legacy), \
                mock.patch.object(app, "Bar", StubBar):
            self.assertEqual(app.main(["--host", "stub", "--test"]), 0)
        self.assertEqual(tree(self.tmp), before)


if __name__ == "__main__":
    unittest.main()
