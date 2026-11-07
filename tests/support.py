"""Shared by every test module, which imports it first.

It puts app.py on the path and, for the whole run, blocks with an audit hook
any access to the real settings: the user's settings folder, the file
$WORKOUT_TIMER_CONFIG names, and the old config.json next to app.py. Each
module's tearDownModule (this one) also fails if a test touched them and
the code under test swallowed the error.

Below the guard are the helpers that several test files share: times as
text, the menu's order of fields, a hand on the bar, a running workout, the
blink, the bar's input messages, and main() on a stub bar."""
import contextlib
import copy
import io
import os
import struct
import sys
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
from app import (MENU, MINUTES, RUN, SECONDS, SETTINGS, SUMMARY, TABATA,  # noqa: E402
                 TIME_FIELDS, TYPE_FIELDS, Wheel)

# --- the settings guard ------------------------------------------------------

_env = {k: v for k, v in os.environ.items() if k != "WORKOUT_TIMER_CONFIG"}
REAL_DIRS = {os.path.join(os.path.expanduser("~"), ".config", app.APP),
             os.path.dirname(app.config_path(env=_env))}
REAL_FILES = {app.LEGACY_CONFIG_PATH}
if os.environ.get("WORKOUT_TIMER_CONFIG"):
    REAL_FILES.add(app.config_path())    # a file, not its folder: it may be in /tmp
# event -> (indexes of its path arguments, indexes of its dir_fd arguments)
WATCHED = {"open": ((0,), ()), "os.remove": ((0,), (1,)), "os.rmdir": ((0,), (1,)),
           "os.mkdir": ((0,), (2,)), "os.chmod": ((0,), (2,)), "os.utime": ((0,), (3,)),
           "os.rename": ((0, 1), (2, 3)), "os.link": ((0, 1), (2, 3)),
           "os.symlink": ((1,), (2,)), "os.truncate": ((0,), ()),
           "shutil.rmtree": ((0,), ()), "shutil.move": ((0, 1), ()),
           "shutil.copyfile": ((1,), ())}
touched = []


def is_real(path, relative_to_cwd=True):
    if path is None or isinstance(path, int):
        return False
    try:
        path = os.fsdecode(path)
    except TypeError:
        return False
    if not os.path.isabs(path) and not relative_to_cwd:
        return False            # relative to a dir_fd (rmtree, os.open), not to the cwd
    full = os.path.abspath(path)
    return (full in REAL_FILES or (full.endswith(".tmp") and full[:-4] in REAL_FILES)
            or any(full == d or full.startswith(d + os.sep) for d in REAL_DIRS))


def _audit(event, args):
    if event not in WATCHED:
        return
    path_at, fd_at = WATCHED[event]
    if event == "open":
        relative_to_cwd = isinstance(args[1], str)   # builtins.open; os.open may use dir_fd
    else:
        relative_to_cwd = all(i >= len(args) or args[i] is None for i in fd_at)
    for i in path_at:
        if i < len(args) and is_real(args[i], relative_to_cwd):
            touched.append((event, args[i]))
            raise RuntimeError("test touched the real settings: %s %r" % (event, args[i]))


sys.addaudithook(_audit)


def tearDownModule():
    if touched:
        found = list(touched)
        touched.clear()                  # reported once, by the module that did it
        raise AssertionError("tests touched the real settings: %r" % found)


# --- clocks and times as text ------------------------------------------------

T0 = 1000.0          # the local clock (time.monotonic) when a test starts
BAR0 = 500.0         # the bar's clock (State.timestamp) at that moment


def secs(txt):
    """'m:ss' as seconds."""
    m, s = txt.split(":")
    return int(m) * 60 + int(s)


def mmss(value):
    """Seconds as the menu shows them, 'm:ss'."""
    return app.fmt_time(value)


# --- the menu ----------------------------------------------------------------

def line_of(kind):
    """SPEC 4 as one line: OK moves one place right (a time opens on its
    minutes), BACK one place left (into a time: its seconds)."""
    out = [("type", kind)]
    for field in TYPE_FIELDS[kind]:
        out += [(field, MINUTES), (field, SECONDS)] if field in TIME_FIELDS else [field]
    return out + [SUMMARY]


def to_summary(kind=TABATA):
    """The OK presses from TYPE to the summary: one per place on the line,
    so a time takes two, for its minutes and its seconds."""
    return ["ok"] * (len(line_of(kind)) - 1)


# (s after T0, event): a Tabata's OKs from TYPE, on the summary at 0.8 s.
SUMMARY_PRESSES = [(0.3 + 0.1 * i, event) for i, event in enumerate(to_summary())]


def spot(c):
    """Where the controller is: a screen, ("type", choice), (time field,
    part) or another field."""
    if c.screen != MENU:
        return c.screen
    if c.field == "type":
        return ("type", c.choice)
    if c.field in TIME_FIELDS:
        return (c.field, c.part)
    return c.field


# --- a hand on the bar -------------------------------------------------------

class Held:
    """A burst the bar held back and sent at once."""

    def __init__(self, delta):
        self.delta = delta


class Hand:
    """A Controller driven like a hand: each event `gap` s after the last
    (0.3 s by default, so a turn back is never a contact bounce). Ints are
    live detents, Held(n) a held burst, strings presses, tuples releases.
    `values` are the type's work, rest and rounds."""

    def __init__(self, kind=TABATA, step=5, skip_with="ok", get_ready=5, **values):
        cfg = app.default_config()
        cfg.update(last_type=kind, step=step, skip_with=skip_with, get_ready=get_ready)
        cfg["types"][kind].update(values)
        self.c = app.Controller(cfg)
        self.now, self.bar = T0, BAR0
        self.saves = []

    def __call__(self, *events, gap=0.3):
        for e in events:
            self.now += gap
            self.bar += gap
            if isinstance(e, int):
                e = Wheel(e, self.bar, False)
            elif isinstance(e, Held):
                e = Wheel(e.delta, self.bar, True)
            self.c.handle(e, self.now)
        return self

    def wait(self, seconds):
        """Let `seconds` pass without input."""
        self.now += seconds
        self.bar += seconds
        self.c.update(self.now)
        return self

    def turns(self, way, n, gap=0.3):
        """Turn `n` live detents one way; the time shown after each."""
        out = []
        for _ in range(n):
            self(way, gap=gap)
            out.append(self.shown())
        return out

    def choose(self, choice):
        """Turn the TYPE wheel to `choice`."""
        assert self.c.field == "type", self.c.field
        for _ in range(len(app.MENU_TYPES)):
            if self.c.choice == choice:
                return self
            self(1)
        raise AssertionError("no %r on the TYPE wheel" % choice)

    def to_settings(self):
        return self.choose(SETTINGS)("ok")

    def to_field(self, field):
        """From TYPE to a SETTINGS field."""
        self.to_settings()
        while self.c.field != field:
            self("ok")
        return self

    def save(self):
        """main()'s save step: what it would write, if anything."""
        if self.c.save_due:
            self.saves.append(copy.deepcopy(self.c.cfg))
            self.c.saved()

    def value(self, field=None, kind=None):
        c = self.c
        return c.cfg["types"][kind or c.kind][field or c.field]

    def shown(self, field=None):
        return mmss(self.value(field))

    @property
    def spot(self):
        return spot(self.c)

    @property
    def at(self):
        return self.c.screen, self.c.field, self.c.choice


# --- a running workout -------------------------------------------------------

def running(kind=TABATA, get_ready=5, skip_with="ok", sound=True, **values):
    """A workout started at T0 through the menu; `values` are the type's
    work, rest and rounds."""
    cfg = app.default_config()
    cfg.update(last_type=kind, get_ready=get_ready, skip_with=skip_with, sound=sound)
    cfg["types"][kind].update(values)
    c = app.Controller(cfg)
    c.handle("ok", T0)
    while c.screen == MENU:
        c.handle("ok", T0)
    c.handle("start", T0)
    assert c.screen == RUN
    return c


def stats(w):
    s = w.stats
    return (s.work_seconds, s.rest_seconds, s.rounds_completed)


# --- the blink ---------------------------------------------------------------

# SPEC 6: the part being set is lit 0.5 s after a press that reaches it, 1 s
# after a detent; then 0.5 s off, 0.5 s on.
LIT_AFTER_PRESS = 0.5
LIT_AFTER_DETENT = 1.0
OFF = LIT_AFTER_PRESS + 0.2           # well inside the first off half second
OFFSETS = (0.0, 0.2, 0.45, 0.55, 0.8, 0.95, 1.05, 1.3, 1.45, 1.55, 1.95, 2.05,
           7.3, 7.7, 600.2, 600.6)    # s after a press or detent that assert_rhythm checks


def spec_hidden(part, since, detent):
    """SPEC 6: the part left out `since` s after the press or detent, or None."""
    first = LIT_AFTER_DETENT if detent else LIT_AFTER_PRESS
    if since < first:
        return None
    return part if (since - first) % 1.0 < 0.5 else None


def clock_parts(txt):
    """The clock slots of a menu time `txt` (m:ss or mm:ss), by part."""
    return {SECONDS: {"c0", "c1"}, "colon": {"c2"},
            MINUTES: {"c%d" % i for i in range(3, len(txt))}}


def hidden(c, now):
    """The part of the time on screen that render() leaves out at `now`
    (MINUTES or SECONDS), or None while all of it is drawn. Anything else
    missing, or extra, fails."""
    els = {el["id"]: el for el in app.render(c, now)}
    txt = mmss(c.cfg["types"][c.kind][c.field])
    slots = app.CLOCK_SLOTS[:len(txt)]
    for s in app.CLOCK_SLOTS[len(txt):]:
        if not app.is_blank(els[s]):
            raise AssertionError("%s drawn beside %s" % (s, txt))
    off = {s for s in slots if app.is_blank(els[s])}
    if not off:
        drawn = "".join(els[s]["text"] for s in reversed(slots))
        if drawn != txt:
            raise AssertionError("drew %r for %r" % (drawn, txt))
        return None
    for part, want in ((SECONDS, {"c0", "c1"}), (MINUTES, set(slots[3:]))):
        if off == want:
            return part
    raise AssertionError("left out %s of %s" % (sorted(off), txt))


class BlinkChecks:
    """For a TestCase: the blink as SPEC 6 has it."""

    def assert_rhythm(self, h, at, detent, offsets=OFFSETS, msg=""):
        """The part being set is left out exactly when SPEC 6 says, counted
        from a press at `at` (or, `detent`, a detent)."""
        part = h.c.part
        for dt in offsets:
            self.assertEqual(hidden(h.c, at + dt), spec_hidden(part, dt, detent),
                             "%s %s, %.2f s after the %s" % (msg, part, dt,
                                                             "detent" if detent else "press"))


# --- the bar's input messages ------------------------------------------------
# Encoders written after the emulator's status_ws.js, which matches the device:
# zero values (OK, PRESS, delta 0) are left off the wire.

def varint(n):
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def field_varint(field, value):
    return varint(field << 3) + varint(value)


def field_message(field, msg):
    return varint(field << 3 | 2) + varint(len(msg)) + msg


def stamp(ms):
    """State.timestamp: the bar's clock in ms."""
    return varint(1 << 3 | 1) + struct.pack("<Q", ms)


def state_frame(input_field, msg, stamp_ms=None):
    head = b"" if stamp_ms is None else stamp(stamp_ms)
    return head + field_message(2, field_message(11, field_message(input_field, msg)))


def button(name, release=False):
    code = {"ok": 0, "back": 1, "start": 2}[name]
    msg = (field_varint(1, code) if code else b"") + (field_varint(2, 1) if release else b"")
    return state_frame(1, msg)


def wheel(delta, stamp_ms=None):
    z = ((delta << 1) ^ (delta >> 31)) & 0xFFFFFFFF
    return state_frame(3, field_varint(1, z) if z else b"", stamp_ms)


def switch(position):
    return state_frame(2, field_varint(1, position) if position else b"")


def bar_message(events, stamp_ms=None, stamp_last=False):
    """One message with an update per event: an int is an encoder delta,
    "ok" a press, ("release", "ok") a release, ("switch", n) the switch."""
    def update(e):
        if isinstance(e, int):
            return wheel(e)
        if isinstance(e, tuple):
            return switch(e[1]) if e[0] == "switch" else button(e[1], release=True)
        return button(e)
    head = b"" if stamp_ms is None else stamp(stamp_ms)
    body = b"".join(update(e) for e in events)
    return body + head if stamp_last else head + body


# --- main() on a stub bar ----------------------------------------------------

class MainRun:
    """What run_main() saw. Times are s after T0."""

    def __init__(self):
        self.ctrl = None
        self.draws = []      # (time, [element, ...]) for every draw
        self.wrong = []      # passes after which the bar didn't show what render() gave
        self.states = []     # (time, {clock slot: text}) the bar showed after each pass
        self.plays = []      # (time, sound)
        self.passes = []     # (time, the workout's phase as the pass began, its events)
        self.saves = []      # (time, settings) for every save

    @property
    def draw_times(self):
        return [t for t, _ in self.draws]


def run_main(events, end, cfg=None, wake_early=True, draw_ok=None):
    """Run main() until T0 + end with `events` [(s after T0, event)], on a
    stub bar and input, with a clock that moves only when the loop waits:
    TICK at a time, or to the next event with `wake_early` (as
    InputListener.wait does; without it an event waits for the next pass, as
    when the loop was busy drawing). The bar clears our elements on BACK's
    press and release, as the firmware does; `draw_ok(now)` says whether a
    draw at `now` gets through. `cfg` (default: the defaults) is loaded and
    every save is recorded; no settings file is ever opened."""
    clock = {"now": T0}
    pending = sorted((T0 + t, i, ev) for i, (t, ev) in enumerate(events))
    run, shown, seen = MainRun(), {}, {}

    def at():
        return round(clock["now"] - T0, 3)

    class Ctrl(app.Controller):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            run.ctrl = self

    class StubBar:
        def __init__(self, host, token=None):
            self.base, self.on_screen = host, True

        def draw(self, elements):
            run.draws.append((at(), [dict(el) for el in elements]))
            self.on_screen = draw_ok is None or draw_ok(clock["now"])
            if self.on_screen:
                shown.update((el["id"], el) for el in elements)
            return self.on_screen

        def play(self, sound):
            run.plays.append((at(), sound))

        install_sounds = lambda self: True          # noqa: E731
        clear = lambda self: None                   # noqa: E731

    def check():
        if "pass" in seen:
            want = sorted(repr(el) for el in app.render(run.ctrl, seen["pass"])
                          if not app.is_blank(el))
            have = sorted(repr(el) for el in shown.values() if not app.is_blank(el))
            if want != have:
                run.wrong.append(round(seen["pass"] - T0, 3))
            run.states.append((seen["pass"] - T0,
                               {s: shown[s]["text"] for s in app.CLOCK_SLOTS
                                if s in shown and not app.is_blank(shown[s])}))

    class StubListener:
        def __init__(self, host, token=None):
            pass

        start = stop = lambda self: None

        def poll(self):
            check()
            seen["pass"] = clock["now"]
            out = []
            while pending and pending[0][0] <= clock["now"] + 1e-9:
                ev = pending.pop(0)[2]
                if ev in ("back", ("release", "back")):
                    shown.clear()                       # the firmware's own BACK
                out.append(ev)
            w = run.ctrl.workout
            run.passes.append((at(), w and w.phase, out))
            return out

        def wait(self, timeout):
            nxt = clock["now"] + timeout
            if wake_early and pending and pending[0][0] < nxt:
                nxt = pending[0][0]
            clock["now"] = nxt
            if clock["now"] > T0 + end:
                check()
                raise KeyboardInterrupt

    def save(c):
        run.saves.append((at(), copy.deepcopy(c)))
        return True

    def no_file(*a, **k):
        raise AssertionError("a settings file was touched")

    with mock.patch.object(app, "Bar", StubBar), \
            mock.patch.object(app, "InputListener", StubListener), \
            mock.patch.object(app, "Controller", Ctrl), \
            mock.patch.object(app, "config_path", lambda *a, **k: "/nonexistent/wt.json"), \
            mock.patch.object(app, "legacy_config_path", lambda *a, **k: None), \
            mock.patch.object(app, "open_settings",
                              lambda *a, **k: (cfg or app.default_config(), save)), \
            mock.patch.object(app, "load_config", no_file), \
            mock.patch.object(app, "save_config", no_file), \
            mock.patch.object(app.time, "monotonic", lambda: clock["now"]), \
            mock.patch.object(app.signal, "signal"), \
            contextlib.redirect_stdout(io.StringIO()):
        app.main(["--host", "stub"])
    return run
