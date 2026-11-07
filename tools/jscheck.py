#!/usr/bin/env python3
"""Jscheck: drive the JavaScript app on a real bar and compare its LEDs.

Development tool only; not part of the app.

    python3 tools/jscheck.py          # bar over USB, app installed (js-app: npm run app:install)
    python3 tools/jscheck.py --soak 300
    python3 tools/jscheck.py --sound     # also lets the workout's sounds play, out loud

Presses simulated keys (POST /api/input) and reads the LEDs (GET /api/screen). Each
screen must match, pixel by pixel, what app.py, the Python app, renders for the same
state through tools/screen.py. A timed workout is checked against the clock as well.

It starts the app from default settings and removes its saved settings and its Setup
values at the end, then leaves the app running. Physical buttons and how it sounds need a person:
see docs/release-checklist.md.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import app  # noqa: E402
import screen  # noqa: E402

# The JS app has no SETTINGS on its wheel: those moved to the bar's Setup page.
app.MENU_TYPES = app.TYPES

HOST = "10.0.4.20"
ID = "app.teunbruijnen.workout_timer"
SAVED = "/ext/apps_data/jsrunner/%s.localstorage.json" % ID
SETUP = "/ext/apps_data/jsrunner/%s.settings.json" % ID
SHORT_READY = {"get_ready": 2, "sound": False, "step": "5", "skip_with": "ok"}  # Setup values for quick, quiet runs
SETTLE = 2.0           # s a screen has to appear in; a blink shows within 1 s
LAG = 0.45             # s the LEDs may trail the clock: the 10 Hz loop, then a full draw
MISMATCH_RUN = 0.05    # s of LEDs matching no frame: the state between a draw's elements shows this long
KEY_GAP = 0.12         # s between keys: a detent turned back within 80 ms counts as a bounce
failures = 0


def report(ok, name, detail=""):
    global failures
    failures += 0 if ok else 1
    print("%-5s %s%s" % ("ok" if ok else "FAIL", name, "  (%s)" % detail if detail else ""), flush=True)


def call(method, path, body=None):
    req = urllib.request.Request("http://%s/api%s" % (HOST, path), method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.read()


def leds():
    return screen.device_grid(HOST)


def grid(elements):
    return screen.render(elements)


def wait_for(wanted, timeout=SETTLE):
    """Poll until the LEDs show one of the grids in `wanted`."""
    deadline = time.monotonic() + timeout
    got = leds()
    while got not in wanted and time.monotonic() < deadline:
        time.sleep(0.03)
        got = leds()
    return got in wanted, got


class Session:
    """The Python app's Controller kept in step with the bar: same inputs, far enough
    apart that no grace or bounce window applies."""

    def __init__(self, cfg=None):
        self.ctrl = app.Controller(cfg or app.default_config())
        self.now = 1000.0

    def press(self, key):
        self.now += 10
        event = {"up": app.Wheel(1, self.now, False), "down": app.Wheel(-1, self.now, False)}.get(key, key)
        self.ctrl.handle(event, self.now)
        self.ctrl.sounds.clear()
        time.sleep(KEY_GAP)
        status, _ = call("POST", "/input?key=" + key)
        if status != 200:
            report(False, "input " + key, "HTTP %d" % status)

    def wanted(self):
        """The grids the screen may show: a time being set blinks."""
        c = self.ctrl
        if c.screen == app.MENU:
            frames = [app.render_menu(c.cfg, c.field, c.choice, None)]
            if c.field in app.TIME_FIELDS:
                frames.append(app.render_menu(c.cfg, c.field, c.choice, c.part))
            return [grid(f) for f in frames]
        if c.screen == app.SUMMARY:
            return [grid(app.render_summary(c.cfg))]
        if c.screen == app.RECAP:
            return [grid(app.render_recap(c.workout, c.recap_page(self.now)))]
        raise ValueError("no fixed frame on screen " + c.screen)

    def step(self, keys, name):
        """Press each key; every screen on the way must match."""
        good = True
        for key in keys.split():
            c = self.ctrl
            if key == "back" and c.screen == app.MENU and c.field == "type":
                raise ValueError("BACK on TYPE would close the app: " + name)
            self.press(key)
            ok, got = wait_for(self.wanted())
            if not ok:
                good = False
                print("after %s, %s:\n%s\nwanted:\n%s" % (key, self.describe(), screen.to_ascii(got),
                                                          screen.to_ascii(self.wanted()[0])))
        report(good, name)

    def describe(self):
        c = self.ctrl
        if c.screen == app.MENU:
            return "%s %s" % (c.field.upper(), app.field_value(c.cfg, c.field, c.choice)[0] or "unlimited")
        return c.screen


def as_config(saved, setup):
    """What the app runs with: its own saved values, and the Setup page's."""
    return app.clean_config({**saved, **setup, "step": int(setup["step"])})


def launch(fresh=False, setup=None):
    call("POST", "/apps/quit")
    if fresh:
        call("DELETE", "/storage/remove?path=" + SAVED)
        call("DELETE", "/storage/remove?path=" + SETUP)
    if setup:
        # Stop rather than go on: without these values the workouts below would play out loud.
        status, _ = call("PUT", "/apps/settings?app_id=" + ID, {"version": 1, "values": setup})
        got, body = call("GET", "/apps/settings?app_id=" + ID)
        if status != 200 or got != 200 or json.loads(body).get("values") != setup:
            sys.exit("cannot set the Setup values: PUT %d, GET %d" % (status, got))
    time.sleep(0.5)
    status, body = call("POST", "/apps/launch?app_id=" + ID)
    if status != 200:
        sys.exit("cannot launch %s: HTTP %d %s; install it first" % (ID, status, body.decode()))


def timeline(kind, work, rest, rounds, get_ready, until=None):
    """([(time, grid)], end, workout) of a workout left to run, at every distinct screen."""
    w = app.Workout(kind, work=work, rest=rest, rounds=rounds, get_ready=get_ready)
    w.start(0.0)
    frames, t = [], 0.0
    while True:
        w.update(t)
        if not w.running or (until is not None and t >= until):
            return frames, t, w
        shown = grid(app.render_workout(w, t))
        if not frames or frames[-1][1] != shown:
            frames.append((t, shown))
        t = round(t + 0.05, 2)


def check_run(name, frames, end):
    """After START: sample the LEDs until `end`; each sample must be a frame due by the
    clock, in order, or a passing mix while a partial draw lands."""
    t0 = time.monotonic()
    seen, lag_max, last_index, bad_since, bad_run, samples = set(), 0.0, 0, None, 0.0, 0
    while True:
        elapsed = time.monotonic() - t0
        if elapsed > end - 0.05:
            break
        got = leds()
        read_at = time.monotonic() - t0
        samples += 1
        match = None
        for i in range(last_index, len(frames)):
            if frames[i][1] == got and frames[i][0] <= read_at + 0.1:
                match = i
        if match is None:
            if not seen:
                continue          # the screen before START, until the first draw lands
            if bad_since is None:
                bad_since = read_at
                print("no frame at %.2f s:\n%s" % (read_at, screen.to_ascii(got)))
            bad_run = max(bad_run, read_at - bad_since)
        else:
            bad_since = None
            next_due = frames[match + 1][0] if match + 1 < len(frames) else end
            lag_max = max(lag_max, read_at - next_due)
            seen.add(match)
            last_index = match
    report(bad_run <= MISMATCH_RUN, name + ": every sample a frame due by the clock",
           "%d samples, longest gap %.2f s" % (samples, bad_run))
    report(lag_max <= LAG, name + ": on time", "LEDs at most %.2f s behind" % max(lag_max, 0))
    report(len(seen) >= 0.8 * len(frames), name + ": frames seen",
           "%d of %d distinct screens" % (len(seen), len(frames)))


def region(elements_grid, got, rows, cols):
    return all(elements_grid[y][x] == got[y][x] for y in rows for x in cols)


def main(argv=None):
    global HOST
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default=HOST)
    p.add_argument("--soak", type=int, default=0, help="also run an unlimited workout this many seconds")
    p.add_argument("--sound", action="store_true", help="play the workout's sounds and check the completed one starts")
    args = p.parse_args(argv)
    HOST = args.host

    print("--- the menu")
    launch(fresh=True)
    s = Session()
    ok, got = wait_for(s.wanted())
    report(ok, "starts on TYPE TABATA, default settings")
    status, body = call("GET", "/apps/settings?app_id=" + ID)
    values = json.loads(body).get("values", {}) if status == 200 else {}
    report(values == {"get_ready": 5, "sound": True, "step": "5", "skip_with": "ok"}, "Setup defaults", json.dumps(values))
    s.step("up up up down", "TYPE wheel wraps both ways, three types")
    s.step("up ok back", "TABATA, WORK minutes, BACK to TYPE")

    print("--- the Setup page's values reach the app")
    other = {"get_ready": 1, "sound": False, "step": "10", "skip_with": "start"}
    launch(setup=other)
    s = Session(as_config({}, other))
    wait_for(s.wanted())
    s.step("ok ok up", "WORK seconds move by the Setup step")
    s.step("back back", "back to TYPE")
    s.step("ok ok ok ok ok ok", "on to the summary")
    call("POST", "/input?key=start")
    time.sleep(1.5)   # past get-ready, in WORK
    status, _ = call("POST", "/input?key=ok")
    time.sleep(0.4)
    paused = app.frame({"label": app.left_text("label", "PAUSE", app.ROW_LABEL, app.COLOR_PAUSED)})
    report(region(grid(paused), leds(), range(0, 5), range(0, 27)), "SKIP WITH START: OK pauses")
    call("POST", "/input?key=back")
    time.sleep(0.3)
    call("POST", "/input?key=back")

    if args.sound:
        SHORT_READY["sound"] = True
    launch(fresh=True, setup=SHORT_READY)
    s = Session(as_config({}, SHORT_READY))
    wait_for(s.wanted())
    s.step("ok", "TABATA, WORK minutes")
    s.step("down up", "minutes wrap 0 -> 59 -> 0")
    s.step("ok down down down", "WORK seconds to 0:05")
    s.step("down up", "seconds wrap 0:05 -> 0:55 -> 0:05")
    s.step("ok ok down", "REST seconds to 0:05")
    s.step("ok down down down down down down", "ROUNDS 8 -> 2")
    s.step("back back back back", "BACK through REST seconds, REST minutes, WORK seconds, WORK minutes")
    s.step("ok ok ok ok", "OK forward to ROUNDS")
    s.step("ok", "summary 5/5 x2")
    s.step("back ok", "summary BACK to ROUNDS, OK again")
    s.step("ok", "OK does nothing on the summary")

    print("--- BACK: the firmware takes the screen, the app takes it back")
    s.step("back", "BACK to ROUNDS")
    wanted = s.wanted()
    samples = [leds() for _ in range(25)]
    report(all(g in wanted for g in samples), "the screen holds after BACK", "%d samples" % len(samples))
    s.step("ok", "summary")

    print("--- a workout left to run: get-ready, 2 rounds, recap")
    t = s.ctrl.cfg["types"][app.TABATA]
    frames, end, finished = timeline(app.TABATA, t["work"], t["rest"], t["rounds"], s.ctrl.cfg["get_ready"])
    report(end == 17.0, "what should happen", "2 s ready, 5 s work, 5 s rest, 5 s work: %.0f s" % end)
    call("POST", "/input?key=start")
    check_run("Tabata", frames, end)

    print("--- the recap")
    recap_grids = {page: grid(app.render_recap(finished, page)) for page in app.RECAP_PAGES}
    ok, got = wait_for(list(recap_grids.values()), 2.0)
    report(ok, "recap appears, with the Python app's numbers")
    status, _ = call("DELETE", "/audio/play")
    if args.sound:
        report(status == 200, "the completed sound is playing (this check stops it)", "DELETE audio/play: %d" % status)
    else:
        report(status == 410, "SOUND off: nothing plays at the end", "DELETE audio/play: %d" % status)
    time.sleep(1.2)   # past the recap's grace
    seen_pages = set()
    for _ in range(50):
        got = leds()
        seen_pages.update(page for page, g in recap_grids.items() if g == got)
        if len(seen_pages) >= 2:
            break
        time.sleep(0.1)
    report(len(seen_pages) >= 2, "recap pages by itself", ", ".join(sorted(seen_pages)))

    def page_now():
        got = leds()
        return next((page for page, g in recap_grids.items() if g == got), None)

    call("POST", "/input?key=ok")
    time.sleep(0.4)
    first = page_now()
    call("POST", "/input?key=up")
    time.sleep(0.4)
    second = page_now()
    time.sleep(3.3)
    third = page_now()
    order = list(app.RECAP_PAGES)
    report(None not in (first, second, third) and second == order[(order.index(first) + 1) % 4] and third == second,
           "OK and the wheel turn pages; then it stops paging by itself", "%s > %s > %s" % (first, second, third))
    s.ctrl.screen, s.ctrl.field, s.ctrl.choice = app.MENU, "type", s.ctrl.kind
    call("POST", "/input?key=back")
    ok, _ = wait_for(s.wanted())
    report(ok, "BACK on the recap: TYPE, that workout's type selected")

    print("--- pause, skip, stop")
    s.step("ok ok ok ok ok", "the way to ROUNDS")
    s.step("up", "ROUNDS 3")
    s.step("ok", "summary")
    call("POST", "/input?key=start")
    time.sleep(0.4)
    call("POST", "/input?key=ok")                             # skip get-ready, into WORK
    time.sleep(0.4)
    label_rows, label_cols = range(0, 5), range(0, 25)
    want = grid(app.frame({"label": app.left_text("label", "WORK", app.ROW_LABEL, app.COLOR_WORK)}))
    report(region(want, leds(), label_rows, label_cols), "OK skips get-ready: WORK")
    call("POST", "/input?key=start")
    time.sleep(0.3)
    want = grid(app.frame({"label": app.left_text("label", "PAUSE", app.ROW_LABEL, app.COLOR_PAUSED)}))
    report(region(want, leds(), label_rows, label_cols), "START pauses: PAUSE, grey")
    seen = []
    for _ in range(20):
        got = leds()
        if got not in seen:
            seen.append(got)
        time.sleep(0.15)
    report(len(seen) == 2, "paused: the time blinks, and stands still", "%d different screens in 3 s" % len(seen))
    call("POST", "/input?key=ok")
    time.sleep(0.3)
    report(region(want, leds(), label_rows, label_cols), "OK is ignored while paused")
    call("POST", "/input?key=start")
    time.sleep(0.3)
    want = grid(app.frame({"label": app.left_text("label", "WORK", app.ROW_LABEL, app.COLOR_WORK)}))
    report(region(want, leds(), label_rows, label_cols), "START resumes")
    call("POST", "/input?key=ok")
    time.sleep(0.3)
    want = grid(app.frame({"label": app.left_text("label", "REST", app.ROW_LABEL, app.COLOR_REST)}))
    report(region(want, leds(), label_rows, label_cols), "OK skips WORK: REST")
    call("POST", "/input?key=back")
    time.sleep(0.4)
    want = grid(app.frame({"label": app.left_text("label", "STOP?", app.ROW_LABEL, app.COLOR_STOP)}))
    report(region(want, leds(), label_rows, label_cols), "BACK: STOP?")
    time.sleep(3.2)
    want = grid(app.frame({"label": app.left_text("label", "REST", app.ROW_LABEL, app.COLOR_REST)}))
    report(region(want, leds(), label_rows, label_cols), "STOP? times out after 3 s; the workout carried on")
    call("POST", "/input?key=back")
    time.sleep(0.3)
    call("POST", "/input?key=back")
    time.sleep(0.5)
    note = app.frame({"note": app.corner("STOPPED", app.COLOR_STOP)})
    report(region(grid(note), leds(), range(0, 5), range(45, 72)), "BACK BACK: the recap says STOPPED")
    s.ctrl.screen, s.ctrl.field, s.ctrl.choice = app.MENU, "type", s.ctrl.kind
    call("POST", "/input?key=back")
    ok, _ = wait_for(s.wanted())
    report(ok, "BACK: TYPE")

    print("--- settings survive a restart; BACK on TYPE closes the app")
    status, body = call("GET", "/storage/read?path=" + SAVED)
    saved = json.loads(json.loads(body)["data"]["config"]) if status == 200 else {}
    report(saved.get("types", {}).get(app.TABATA, {}).get("rounds") == 3, "saved on the bar", json.dumps(saved.get("types", {}).get(app.TABATA)))
    report(sorted(saved) == ["last_type", "types"], "only the app's own values are saved", ", ".join(sorted(saved)))
    ours = s.wanted()
    call("POST", "/input?key=back")
    # apps/quit can't tell: on firmware 1.3.1 it answers 200 even after an app released
    # everything. So: no redraw past the 5 s refresh, and it can be launched again.
    time.sleep(0.5)
    away = [leds() not in ours]
    for _ in range(14):
        time.sleep(0.5)
        away.append(leds() not in ours)
    report(all(away), "BACK on TYPE closes: the bar's screen, no redraw for 7 s")
    status, _ = call("POST", "/apps/launch?app_id=" + ID)
    again = Session(as_config(saved, SHORT_READY))
    ok, _ = wait_for(again.wanted())
    report(status == 200 and ok, "and it launches again without a quit first", "HTTP %d" % status)
    again.step("ok back", "and answers buttons, once each")
    launch()
    fresh = Session(as_config(saved, SHORT_READY))
    ok, _ = wait_for(fresh.wanted())
    report(ok, "launched again: on the last type")
    fresh.step("ok ok ok ok ok", "with the saved values")

    print("--- an open phase: Fixed rest counts up until OK")
    launch()
    s = Session(as_config(saved, SHORT_READY))
    wait_for(s.wanted())
    s.step("up ok", "FIXED REST, REST minutes")
    s.step("ok ok ok", "to the summary")
    rest = s.ctrl.cfg["types"][app.FIX_REST]
    frames, end, _ = timeline(app.FIX_REST, rest["work"], rest["rest"], rest["rounds"], s.ctrl.cfg["get_ready"], until=6.0)
    call("POST", "/input?key=start")
    check_run("Fixed rest", frames, end)
    call("POST", "/input?key=back")
    time.sleep(0.3)
    call("POST", "/input?key=back")
    time.sleep(0.5)
    note = app.frame({"note": app.corner("STOPPED", app.COLOR_STOP)})
    report(region(grid(note), leds(), range(0, 5), range(45, 72)), "stopped from the open phase")

    if args.soak:
        print("--- soak: an unlimited workout for %d s" % args.soak)
        launch(fresh=True, setup=SHORT_READY)
        s = Session(as_config({}, SHORT_READY))
        wait_for(s.wanted())
        s.step("ok ok ok ok ok", "default Tabata to ROUNDS")
        s.step("down down down down down down down down", "ROUNDS 8 -> unlimited")
        s.step("ok", "summary")
        call("POST", "/input?key=start")
        t0, last, frozen_max, changed_at = time.monotonic(), leds(), 0.0, time.monotonic()
        while time.monotonic() - t0 < args.soak:
            got = leds()
            now = time.monotonic()
            if got != last:
                last, changed_at = got, now
            frozen_max = max(frozen_max, now - changed_at)
            time.sleep(0.2)
        report(frozen_max < 1.5, "still counting at the end", "screen never still for more than %.1f s" % frozen_max)
        call("POST", "/input?key=back")
        time.sleep(0.3)
        call("POST", "/input?key=back")
        time.sleep(0.6)
        note = app.frame({"note": app.corner("STOPPED", app.COLOR_STOP)})
        report(region(grid(note), leds(), range(0, 5), range(45, 72)), "still answers buttons")

    launch(fresh=True)
    print("%d failures" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
