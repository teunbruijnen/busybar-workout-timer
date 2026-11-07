"""Device I/O: drawing must never raise, whatever the bar answers."""
import http.server
import json
import os
import socket
import sys
import threading
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from support import tearDownModule  # noqa: E402,F401  (first: guards the real settings)
from support import T0, run_main, to_summary  # noqa: E402
import app  # noqa: E402

FRAME = [app.text("t", "HI")]


class FakeBar(http.server.ThreadingHTTPServer):
    """Answers every request with `status` and records what it was sent."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), FakeHandler)
        self.status = 200
        self.truncate = False             # promise more body than is sent
        self.requests = []
        self.folders = {}                 # storage: folder -> {name: bytes}

    @property
    def host(self):
        return "127.0.0.1:%d" % self.server_address[1]


class FakeHandler(http.server.BaseHTTPRequestHandler):
    def _answer(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.requests.append((self.command, self.path, self.headers, body))
        payload = b'{"result":"OK"}' if self.server.status == 200 else b'{"error":"nope"}'
        self.send_response(self.server.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload) + 100 * self.server.truncate))
        self.end_headers()
        self.wfile.write(payload)
        if self.server.truncate:
            self.close_connection = True

    do_POST = do_DELETE = _answer

    def do_GET(self):
        # /api/storage/list and /api/storage/read over `folders`.
        url = urllib.parse.urlparse(self.path)
        path = urllib.parse.parse_qs(url.query)["path"][0]
        self.server.requests.append((self.command, self.path, self.headers, b""))
        folder, _, name = path.rpartition("/")
        status, payload = 400, b'{"error":"Bad Request"}'
        if url.path == "/api/storage/list" and path in self.server.folders:
            files = self.server.folders[path]
            status, payload = 200, json.dumps({"list": [
                {"type": "file", "name": n, "size": len(b)} for n, b in files.items()]}).encode()
        elif url.path == "/api/storage/read" and name in self.server.folders.get(folder, {}):
            status, payload = 200, self.server.folders[folder][name]
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class BarTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeBar()
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()
        self.logs = []
        self.bar = app.Bar(self.server.host, log=self.logs.append)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_draw_sends_app_name_priority_and_ids(self):
        self.assertTrue(self.bar.draw(FRAME))
        method, path, _, body = self.server.requests[0]
        self.assertEqual((method, path), ("POST", "/api/display/draw"))
        sent = json.loads(body)
        self.assertEqual(sent["application_name"], "workout-timer")
        self.assertEqual(sent["priority"], app.PRIORITY)
        self.assertTrue(all("id" in el for el in sent["elements"]))

    def test_409_is_quiet_and_reported_once(self):
        self.server.status = 409
        self.assertFalse(self.bar.draw(FRAME))
        self.assertFalse(self.bar.on_screen)
        self.assertFalse(self.bar.draw(FRAME))
        self.assertEqual(len(self.logs), 1)
        self.server.status = 200
        self.assertTrue(self.bar.draw(FRAME))
        self.assertIn("display back", self.logs[-1])

    def test_a_cut_off_answer_does_not_raise(self):
        # http.client.IncompleteRead is not an OSError: it used to escape.
        self.server.truncate = True
        self.assertFalse(self.bar.draw(FRAME))
        self.bar.play(app.SOUND_TICK)
        self.bar.clear()
        self.assertFalse(self.bar.on_screen)

    def test_only_a_successful_draw_puts_the_app_back_on_screen(self):
        self.server.status = 409
        self.bar.draw(FRAME)
        self.server.status = 200
        self.bar.play(app.SOUND_TICK)
        self.bar.install_sounds()
        self.bar.clear()
        self.assertFalse(self.bar.on_screen)
        self.assertTrue(self.bar.draw(FRAME))
        self.assertTrue(self.bar.on_screen)

    def test_other_http_errors_do_not_raise(self):
        self.server.status = 400
        self.assertFalse(self.bar.draw(FRAME))
        self.assertFalse(self.bar.on_screen)

    def test_token_goes_in_header(self):
        bar = app.Bar(self.server.host, token="s3cret", log=self.logs.append)
        bar.draw(FRAME)
        self.assertEqual(self.server.requests[0][2].get("X-API-Token"), "s3cret")

    def test_clear_deletes_own_elements(self):
        self.bar.clear()
        method, path, _, _ = self.server.requests[0]
        self.assertEqual(method, "DELETE")
        self.assertEqual(path, "/api/display/draw?application_name=workout-timer")


class SoundTest(unittest.TestCase):
    SOURCE = {"countdown_tick.snd": b"t" * 10, "countdown_finish.snd": b"f" * 8,
              "session_completed.snd": b"c" * 20, "other.snd": b"o"}

    def setUp(self):
        self.server = FakeBar()
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()
        self.logs = []
        self.bar = app.Bar(self.server.host, log=self.logs.append)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def uploads(self):
        return {urllib.parse.parse_qs(urllib.parse.urlparse(path).query)["file"][0]: body
                for method, path, _, body in self.server.requests
                if path.startswith("/api/assets/upload")}

    def test_copies_the_busy_timer_sounds_into_the_app_assets(self):
        self.server.folders[app.SOUND_SOURCE] = dict(self.SOURCE)
        self.assertTrue(self.bar.install_sounds())
        self.assertEqual(self.uploads(), {n: b for n, b in self.SOURCE.items() if n != "other.snd"})
        upload = next(r for r in self.server.requests if r[1].startswith("/api/assets/upload"))
        self.assertIn("application_name=workout-timer", upload[1])
        self.assertEqual(upload[2]["Content-Type"], "application/octet-stream")

    def test_sounds_already_in_place_are_not_copied_again(self):
        self.server.folders[app.SOUND_SOURCE] = dict(self.SOURCE)
        self.server.folders[app.SOUND_ASSETS] = {"countdown_tick.snd": b"t" * 10,
                                                 "countdown_finish.snd": b"old"}
        self.assertTrue(self.bar.install_sounds())
        self.assertEqual(sorted(self.uploads()), ["countdown_finish.snd", "session_completed.snd"])

    def test_no_busy_timer_sounds_gives_up_quietly(self):
        self.assertTrue(self.bar.install_sounds())          # e.g. the emulator
        self.assertEqual(self.uploads(), {})
        self.assertEqual(len(self.logs), 1)

    def test_play_names_the_app_asset(self):
        self.bar.play(app.SOUND_FINISH)
        method, path, _, body = self.server.requests[0]
        self.assertEqual((method, path), ("POST", "/api/audio/play"))
        self.assertEqual(json.loads(body), {"application_name": "workout-timer",
                                            "path": "countdown_finish.snd"})

    def test_play_failures_are_reported_once(self):
        self.server.status = 404
        self.bar.play(app.SOUND_TICK)
        self.bar.play(app.SOUND_TICK)
        self.assertEqual(len(self.logs), 1)


class UnreachableBarTest(unittest.TestCase):
    def test_connection_refused_does_not_raise(self):
        with socket.socket() as s:          # grab a free port, then let it go
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        logs = []
        bar = app.Bar("127.0.0.1:%d" % port, log=logs.append)
        self.assertTrue(bar.on_screen)       # until a draw says otherwise
        self.assertFalse(bar.draw(FRAME))
        self.assertFalse(bar.on_screen)
        bar.clear()                          # must not raise either
        bar.play(app.SOUND_TICK)
        self.assertFalse(bar.install_sounds())               # try again later
        self.assertEqual(len(logs), 2)                       # draw, play


class MainLoopSoundTest(unittest.TestCase):
    """main() with a stub bar and input, on a clock that moves only when the
    loop waits: a Tabata started from the menu at once, whose first WORK
    ends 7 s in, with a tick on each of its last 3 s and the finish sound at
    the end."""
    SOUNDS_DUE = [app.SOUND_TICK] * 3 + [app.SOUND_FINISH]

    def played(self, draws_fail_from=float("inf"), draws_fail_until=float("inf")):
        """The sounds played when draws fail in [draws_fail_from, draws_fail_until)
        (for any reason: Bar.on_screen doesn't tell them apart)."""
        cfg = app.default_config()
        cfg["get_ready"] = 0
        cfg["types"][app.TABATA]["work"] = 7
        run = run_main([(0, e) for e in to_summary() + ["start"]], end=9, cfg=cfg,
                       draw_ok=lambda now: not draws_fail_from <= now < draws_fail_until)
        return [sound for _, sound in run.plays]

    def test_due_sounds_play_while_the_bar_answers(self):
        self.assertEqual(self.played(), self.SOUNDS_DUE)

    def test_due_sounds_are_dropped_while_draws_fail(self):
        # Draws fail from the start: held off 0-1, 1-2, ..., so each sound
        # comes due just as a hold ends, before the next draw fails again;
        # the last draw failed, so it is dropped all the same.
        self.assertEqual(self.played(draws_fail_from=T0), [])

    def test_due_sounds_are_dropped_inside_a_hold(self):
        # Draws fail (e.g. refused: another app owns the display) from 0.55 s
        # on: held off 0.6-1.6, 1.6-2.6, ..., so every sound comes due inside
        # a hold.
        self.assertEqual(self.played(draws_fail_from=T0 + 0.55), [])

    def test_sounds_come_back_with_the_bar(self):
        # Draws fail from 3.5 s to 5.3 s: held off 3.5-4.5 and 4.5-5.5, so the
        # ticks at 4 and 5 s are dropped (never played late); the bar answers
        # again at 5.5, and the tick at 6 s and the finish at 7 s play.
        plays = self.played(draws_fail_from=T0 + 3.45, draws_fail_until=T0 + 5.3)
        self.assertEqual(plays, [app.SOUND_TICK, app.SOUND_FINISH])

    def test_a_sound_waits_for_its_own_pass_draw(self):
        # The draw at 7 s (the new REST on screen) fails, though the one
        # before it worked: the finish sound due then is dropped.
        plays = self.played(draws_fail_from=T0 + 6.95, draws_fail_until=T0 + 7.05)
        self.assertEqual(plays, [app.SOUND_TICK] * 3)


if __name__ == "__main__":
    unittest.main()
