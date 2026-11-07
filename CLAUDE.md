# CLAUDE.md

Project context for Claude Code and other coding agents, and a map for anyone reading the code. Read this first, then `SPEC.md`.

## What this project is
A workout interval timer for the BUSY Bar (Flipper's desk device with a 72×16 RGB LED matrix): three timer types (Tabata, Fixed rest, Fixed work), set up on the bar, with an end-of-workout recap. `SPEC.md` defines the JavaScript app's behaviour; the Decisions and Conventions below cover what only `app.py` has. If the code and the spec disagree, raise it; don't guess.

There are two versions:
- **`js-app/`, the JavaScript app.** It runs on the bar itself. **New work goes here.**
- **`app.py`, the Python app.** It runs on a computer and draws on the bar over HTTP. It stays as the reference: `npm test` replays random sessions through it and compares every state, frame, sound and draw plan with the JavaScript app. A behaviour change therefore lands in both, or the differential test fails. `SPEC.md` section 8 lists how the two differ.

## Getting set up
- JavaScript app: Node 24 (Node 26 is not supported). In `js-app`, run `npm install`.
- Python app and its tests: Python 3.9+, nothing to install. Always write `python3`.
- Reference clones, git-ignored and read-only. `tools/screen.py` and what uses it (`gallery.py`, `hwcheck.py`, `jscheck.py`, `make_preview.py`) need the emulator's font atlas, and two tests in `tests/test_render.py` skip without it. **Never edit `reference/`.** Search tools may skip it, so read files by explicit path.
  ```bash
  git clone https://github.com/maxswinkels/busybar-emulator reference/busybar-emulator
  git clone https://github.com/maxswinkels/busybar-apps reference/busybar-apps
  git clone https://github.com/busy-app/busylib-py reference/busylib
  git clone https://github.com/maxswinkels/busybar-manager reference/busybar-manager
  ```
- `reference/busybar-apps/apps/` has community apps that show structure, input and drawing (`clock`, `countdown`, `pixel-runner`, `counter`), and its `CONTRIBUTING.md` has the app conventions the Python app follows.
- What needs what: `npm test` (it runs `app.py`, so it needs `python3`) and `python3 -m unittest discover tests` need no bar and no `reference/`. `tools/gallery.py` and `tools/make_preview.py` need `reference/` but no bar. `npm run app:*` needs a bar, and `tools/jscheck.py` and `tools/hwcheck.py` need both. Without a bar you get the tests, and `app.py` on the emulator. Over USB, a bar is always at `10.0.4.20`.

## Project structure
- `js-app/`: the JavaScript app: `src/` the app, `test/` its tests, `tools/` the test oracle, the icon maker and the release clean-up.
- `app.py`: the Python app, one stdlib-only file, in sections marked `# --- ... ---`:
  - Pure logic (no I/O, no clock reads; time-dependent methods take `now`):
    - timer logic: `Workout` (the state machine) and `Stats`.
    - settings: defaults, validation of `config.json` (`clean_config`), wheel steps.
    - controller: `Controller`, which owns the menu flow, buttons, wheel filtering (contact bounces; large held bursts on the recap), the STOP? prompt, recap paging and sound cues.
  - Device I/O: `Bar` (HTTP: draw, copy and play sounds, clear), `load_config`/`save_config`, `decode_input` and `InputListener` (the input WebSocket, in a daemon thread that only queues events).
  - Rendering: `render(ctrl, now)` and the `render_*` functions; `frame()` lays a screen over fixed element slots; `Painter` works out which elements changed.
  - App: `DrawSchedule` (when to draw, refresh, reclaim after BACK, retry; no I/O of its own: draw, sound install and clock are passed in) and `main()`, the ~10 Hz loop that feeds events to the controller and draws.
- `tests/`: unittest suite for `app.py`, one file per area. Put new tests in the file for their area; start a new file only for a new area.
  - `support.py`: imported first by every test module. Puts `app.py` on the path and holds the shared helpers (use them, don't copy them). Tests must never touch the real settings files: its audit hook blocks any access, and its `tearDownModule` fails the module that tried.
  - `test_timer.py`: `Workout`: the three types, pause/resume, early stop, stats, skips in every phase, the late-skip grace.
  - `test_controller.py`: `Controller`: the menu flow, the wheel (bounces, held bursts), SETTINGS, workout buttons, SKIP WITH, skips, STOP?, sounds, recap paging, saving.
  - `test_menu.py`: WORK/REST as minutes then seconds, against models written from SPEC; the OK/BACK walk; the blink; START in the menu; BACK in SETTINGS.
  - `test_grace.py`: late presses: the skip grace, the recap's START/OK grace, BACK after a stop.
  - `test_config.py`: `clean_config`, wheel steps, loading and saving.
  - `test_config_location.py`: where the settings live, the move from the old file, unwritable folders, `main()`'s wiring.
  - `test_input.py`: protobuf decoding, held messages, the WebSocket listener.
  - `test_bar.py`: HTTP to the bar, sounds.
  - `test_render.py`: screens. Two tests skip unless `reference/busybar-emulator` is present.
  - `test_schedule.py`: `DrawSchedule`.
  - `test_main_draws.py`: `main()` end to end, as the bar sees it.
- `tools/`: development tools, not part of the app (see Commands).
- `docs/release-checklist.md`: what to run and check by hand before a release.
- `manifest.yaml`, `preview.gif`: gallery metadata and preview.
- `AGENTS.md`: points other coding agents to this file.
- `config.json` next to `app.py`: the old settings location, read until the first save moves it (see Conventions). Git-ignored.

## Commands
Run and test the Python app:
- Tests: `python3 -m unittest discover tests`
- On a bar over USB: `python3 app.py` (default host `10.0.4.20`)
- Over Wi-Fi: `python3 app.py --host <ip> --token <password>`, or set `BUSY_HTTP_PASSWORD` instead of `--token`.
- On the emulator: `python3 app.py --host 127.0.0.1:8080`
- `--test`: draws one WORK screen and exits (status 0 if the bar accepted it).
- Stop the app with Ctrl-C. Delete `~/.config/workout-timer/config.json` to get the default settings back (also an old `config.json` next to `app.py`, if it hasn't been moved yet). Or run with `WORKOUT_TIMER_CONFIG=/tmp/wt.json` to start from defaults and leave your own settings untouched.

Emulator:
- First time (use `npm ci`; `npm install` rewrites the emulator's lockfile): `cd reference/busybar-emulator/web && npm ci && npm run build && cd ../../..`
- Run: `node reference/busybar-emulator/server.js` → http://127.0.0.1:8080
- Press keys: `curl -X POST '127.0.0.1:8080/api/input?key=ok'`. Keys: `up`/`down` (wheel), `ok`, `back`, `start`.

Dev tools:
- What the emulator shows (PNG + ASCII grid with column ruler): `python3 tools/screen.py --out /tmp/screen.png --ascii`. A port of the emulator's renderer reading its font atlas; `--json file` renders a saved draw body without the emulator. Like the emulator, it ignores text alpha and doesn't draw `xpmbitmap`/images.
- What a real bar shows: `python3 tools/screen.py --device 10.0.4.20 --out /tmp/bar.png --ascii`
- Every screen state in one stacked PNG (needs `reference/`, no bar or running emulator): `python3 tools/gallery.py --out /tmp/gallery.png [--ascii MATCH]`
- Every gallery screen on a real bar against the emulator renderer (stop the app first): `python3 tools/hwcheck.py [--host ...] [--match NAME]`
- `preview.gif`: `python3 tools/make_preview.py --out preview.gif`

Running the Python app elsewhere:
- Standalone: run `python3 app.py` on a computer connected to the bar over USB.
- busybar-manager runs the app as `app.py --host 127.0.0.1:8321`, proxies HTTP and the input WebSocket, stops it with SIGTERM, and restarts it if it exits. It draws at priority 10 unless the variation sets 1–100, replaces the app folder on update and deletes it on removal (a re-upload needs a removal first). To upload it by hand, run `zip workout-timer.zip app.py manifest.yaml` and upload it under Library → gear → Upload app. The slug comes from the zip's name and must be `workout-timer`: the manager applies the variation's priority to draws whose `application_name` matches it. A zip of a folder made with Finder's Compress can be refused (`__MACOSX/` counts as a second top-level folder). Don't add this repo as a local app folder: its slug would be the folder's name.
- Gallery: three files go in unchanged: `app.py`, `manifest.yaml`, `preview.gif`. The gallery takes only an `app.py`, so the JavaScript app can't go there. Never run the gallery tools inside `reference/`; work on a copy. Run each line from the repo root:
  ```bash
  cp -R reference/busybar-apps /tmp/ba      # once
  mkdir -p /tmp/ba/apps/workout-timer && cp app.py manifest.yaml preview.gif /tmp/ba/apps/workout-timer/
  cd /tmp/ba && python3 tools/busycheck.py workout-timer --run
  ```

## The JavaScript app
BUSY's runtime rules are in `js-app/AGENTS.md`.

- In `js-app`: `npm test`, `npm run typecheck`, `npm run build`, `npm run release`, `npm run icons`, `npm run app:install`, `npm run app:uninstall`, `npm run app:run`, `npm run app:stop`. A failed install can leave the app removed; run it again.
- Modules in `js-app/src`: `timer.ts`, `config.ts`, `controller.ts`, `render.ts` and `schedule.ts` are pure; `main.ts` holds the device layer (input, the 10 Hz loop, HTTP, `localStorage`).
- Tests: `js-app/test/differential.test.ts` replays seeded random sessions from `js-app/tools/oracle.py`, which runs `app.py`, and compares state, frames, sounds and draw plans. `js-app/test/app.test.ts` covers what is new.
- From the repo root, `python3 tools/jscheck.py [--soak 300]`: simulated keys on a real bar, LEDs compared with `app.py`'s frames through `tools/screen.py`. It needs `reference/` and resets the app's saved settings and Setup values, so back those up first if you care about them. It runs silent; `--sound` plays the workout's sounds. Never send keys once the app has closed: they reach the bar's home screen.
- Before a release: `docs/release-checklist.md`. Publish the file from `npm run release`, not from `npm run build`: `busy-cli build` writes the build machine's login into the `.tgz`, and the release step blanks it.

### Firmware facts
Checked on firmware 1.3.1, API 27.14.0.
- Clock: only `Date.now()`; no `performance`. `Settings` global: absent. Storage API from an app: 403, even for `/ext/data`. `localStorage` works; from a computer it is `/ext/apps_data/jsrunner/<id>.localstorage.json`, and it survives an update, an uninstall and a reinstall.
- `audio/play` with `path` `sounds/<file>.snd` plays a packaged sound. A missing file gets 404. `stock_path` reaches only `shared/`; `assets/upload` from an app is 403.
- `DELETE audio/play` answers 200 while a sound plays and 410 when none does, so a check can tell it started.
- `POST /api/input?key=` reaches the JS app: a button gives `press`, `short`, `release`; `up`/`down` give one encoder event each.
- A short BACK clears the app's elements and shows the firmware's own "Loading...", at any priority (tested 50, 100) and for any `application_name`; the app keeps running and a draw takes the screen back. Drawing from a computer at full speed still leaves it up about 75 ms, so an app can only shorten it; this app gets it to about 175 ms. Holding the first redraw back makes it worse (tested 30, 80 ms), and so does starting the redraws on `press` for a quick tap. Measured with simulated keys. In the firmware source, not run on a bar: tag `1.3.1` wipes the screen on a short BACK; tag `1.4.0-rc` calls `canvas_set_clear_on_back(false)` while a JS app runs, which should end the flash.
- After an app exits the firmware shows its Start / Setup page, not the home screen. In the list, OK opens that page; on it, START and OK start the app. Setup's button is not one that `POST /api/input` can send (checked `up`, `down`, `ok`, `start`, `settings`), so the Setup screen itself needs a person.
- Setup: `appmeta/settings.json` (`format_version`, `version`, `fields`; types seen: `integer` with `min`/`max`, `boolean`, `enum` with string values, `string`, `geolocation`) makes the firmware's Setup page. `GET /api/apps/settings?app_id=` gives `{version, values}` to the app and to a computer; `PUT` from a computer replaces them. Stored in `/ext/apps_data/jsrunner/<id>.settings.json`. `localhost` and `127.0.0.1` are equally fast from an app.
- Opening new connections at a high rate (about 90 a second) can stall the bar's web server for a minute. Sample the LEDs in short windows with rests between them.
- `POST /api/apps/quit` answers 200 even after an app released everything, and 409 only when none was launched, so it can't prove an app ended.
- A BUSY session started during a workout closes the app.
- A draw does not land whole: the LEDs can show the state between its elements. With the label first and the wipes among the new elements, TYPE to WORK shows a mix for 80-110 ms in one direction, every time; with the wipes first it is rare and short (18-35 ms). Two draws show their in-between state for about 160 ms. Draw time grows with elements: about 25 ms for 1, 45 ms for 6, 125-170 ms for 29.

## Decisions
Why it's built this way. Add new ones here, with the reason.

The JavaScript app:
- BACK on TYPE closes the app: there is no manager to restart an app that exits.
- Own element arrays and plain `fetch` instead of `@busy-app/busy-lib`: the layout is pixel-exact, and the library adds code to a small heap.
- The sounds are committed: the firmware's `REUSE.toml` puts `assets/sounds/**` under CC-BY-SA-4.0, so they can ship with credit, and a build doesn't need a bar. `src/resources/NOTICE.txt` goes into the package with them.
- Icons are made by `npm run icons` (`js-app/tools/make-icons.mjs`) and committed.
- The type settings live in `localStorage`. GET READY, SOUND, TIME STEP and SKIP WITH live in `settings.json`, on the firmware's Setup page: the app doesn't need to write them, only read them at start. `cleanConfig` still accepts those four if `localStorage` holds them: they count until the Setup answer arrives, or for the whole run if that read fails, and go at the next save.
- The app id in `src/appmeta/manifest.json` can't change without leaving users a second app and their settings behind.
- A new screen and the wipes of the old one go in one draw, the wipes first: two draws, or the new screen first, let them show together.
- After BACK, full draws back to back for 0.4 s and no wipes until that ends: the wipes (up to 29 elements) were the slowest draw at the worst moment. BACK stays as the way back through the setup, with no held OK, because the flash is the firmware's. Once firmware 1.4.0 is out, remove the 0.4 s of full draws and re-test. The app must not depend on 1.4.0 before then.
- `steadyClock`: the workout's clock ignores a reading that goes back or jumps more than 10 s.
- A time's colon stays on one column: 49 in the workout, 32 in the setup, the recap stays centred. 49 keeps a blank column beside everything reachable. `app.py` changes in step, because the differential test compares every position.
- A time is cut to whole seconds with a 1e-9 margin, in both apps: phases added up can land just under a whole second, and a recap then shows `0:09` for 10 s. Tests with round start times never hit it.
- The JS app lives in `js-app/` so that the two versions don't collide.

Both apps:
- A pure controller owns the menu flow and buttons; the device layer feeds it events and draws what `render` returns.
- Every element has a fixed slot and one type, and nothing uses the bar's `align`: changing an element's type is refused on the bar, and its centring rounds differently from the emulator.
- Times are drawn as a clock, one element per character in fixed digit cells, so they never shift. `∞` is drawn from rectangles. Text widths come from glyph advance tables.
- OK skips in every timer type and any phase, get-ready included, and is ignored while paused: someone may run Tabata-style workouts with long rounds and want to skip.
- SKIP WITH is OK (default) or START. It's named that because it reads as a sentence and names the button you press; "SWAP OK/START: ON/OFF" needs you to remember the default.
- A skip is ignored for 0.5 s after a phase began by itself, so a press meant for the phase that just ended doesn't skip the next one. A phase begun by a skip has no grace, so a double skip works. The recap ignores START and OK for 1 s, so a late press doesn't restart the workout.
- WORK and REST are set as minutes, then seconds. Every detent is one step, with no speed-up: fast spins froze and felt unnatural on the bar. The part being set blinks (0.5 s lit, 0.5 s off) and stays lit for 1 s after a detent.
- BACK steps back through every part; going forward with OK a time opens on its minutes.
- A stopped workout is silent, but stopping an unlimited one plays the completed sound, since that's how it ends.

The Python app:
- Standard library only, no `requirements.txt`, in a single file, as the community gallery requires. Input over `/api/status/ws` is decoded by hand, so the app is zero-install.
- `/api/...` paths with `X-API-Token`, not the `/busybar/...` + Bearer form in the bar's API spec: every working reference uses `/api/...`.
- Sounds are the BUSY timer's own, copied from the bar at startup, because the bar won't play them for another app from where they live.
- Settings live outside the app folder, because busybar-manager replaces that folder on update and deletes it on removal. The old `config.json` next to `app.py` is deleted on the first save, so that deleting the new file resets to defaults instead of bringing the old settings back.
- BACK on TYPE does nothing, because the manager restarts an app that exits.
- A held message keeps its presses and detents in order: `decode_input` makes each run of detents between presses or releases one `Wheel` with the run's net count, so a held "turn, OK, turn" sends the second turn to the seconds. A held burst moves by its net count, which also cancels contact bounces.
- No demo mode. `tools/make_preview.py` draws `preview.gif`, because the gallery's preview tool can't drive an app that needs buttons.
- A lean `app.py`: comments say why, never what. The module docstring stays because the gallery shows it. Printed and logged text only where a user needs it.

## Conventions
- Python: standard library only. One file, `app.py`, with entrypoint flags `--host <ip[:port]>` (default `10.0.4.20`), `--token`, `--test` (the manager's dashboard turns every flag in `--help` into a control). App id: `workout-timer`.
- Keep three layers apart: pure timer/controller logic, rendering to display elements, device I/O. Tests import the pure parts.
- Python time comes from `time.monotonic()`, apart from arrival stamps when the bar sends no clock. Never accumulate time by counting `sleep()` calls.
- Secrets (Wi-Fi password, API token) only from CLI flags or env vars. Never write them to committed files. `.env` is git-ignored.
- `app.py`'s settings live outside the app folder: `$WORKOUT_TIMER_CONFIG` (a full path; `~` expanded), else `%APPDATA%\workout-timer\config.json` on Windows, else `$XDG_CONFIG_HOME/workout-timer/config.json` (if absolute) or `~/.config/workout-timer/config.json`. Without `$WORKOUT_TIMER_CONFIG`, while the new file doesn't exist, an old `config.json` next to `app.py` is read, and the first save after that writes the new place and deletes it. With the variable set, the old file is never read or touched. A missing or corrupt file falls back to defaults, one value at a time. Writes are atomic (temp file, fsync, rename) and happen on the next button press after a change, and on exit.
- Name constants with a one-line reason (see the timeouts in the I/O section of `app.py`).

## Hardware and API facts (firmware 1.2.4, the Python app)
Verified on firmware 1.2.4 unless noted. Where this disagrees with the firmware facts above, the newer firmware wins.
- Display: 72×16 RGB. Fonts: `tiny`, `small`, `normal`, `condensed`, `bold`, `large`, `extra_large`. Text is printable ASCII only (`∞` is drawn from rectangles).
- Colours are `#RRGGBBAA`; the alpha channel is required. The emulator ignores alpha on text, so dim by colour (paused is `#808080FF`).
- Base URLs:
  - USB: `http://10.0.4.20/api` (no auth)
  - Wi-Fi: `http://<ip>/api` with header `X-API-Token: <password>` (Wi-Fi API access is off by default)
  - Emulator: `http://127.0.0.1:8080/api` (`--host 127.0.0.1:8080`)
- A bar serves its own API spec at `http://<bar>/docs/`: check it before assuming an endpoint, field or event exists. It lists `/busybar/...` paths with Bearer auth (the cloud form); the bar, emulator, reference apps, busylib and this app use `/api/...` with `X-API-Token`.
- Drawing: `POST /api/display/draw` with `application_name` and `elements`. Every element needs an `id`.
  - An element stays until it is replaced, its `timeout` runs out (the app uses 15 s), or the app's elements are cleared. Partial draws work: left-out elements stay as they were.
  - Changing an id's element type (text ↔ rectangle) gets HTTP 400 on the bar and leaves that element and the ones after it unchanged; the emulator allows it. `frame()` enforces one type per slot.
  - The emulator stacks elements in the order their ids first arrived, so the app uses fixed slots and sends `z_index`.
  - A zero-size rectangle is refused.
  - The bar's `align` centring rounds differently from the emulator: position everything yourself.
- Priority: built-in apps 10, this app 50 (the API default; busybar-manager overrides it), an active BUSY or CUSTOM session 90. HTTP 409 on draw means a higher-priority app owns the display: handle it quietly, never crash.
- BACK, for an app running on a computer: on release of a short press the firmware clears all our elements and shows its home screen, whatever the priority (tested 50–89); a long press doesn't. The app redraws at once on press and release. A 50–100 ms glimpse of the home screen remains.
- OK, START and the wheel reach only the app; START doesn't start a BUSY session.
- Input (buttons, wheel) for an app on a computer is **not** in the API spec: it arrives on the WebSocket `/api/status/ws` (send `{"enable": true}`, then decode protobuf). Verified via the reference apps, the emulator's `status_ws.js` and busylib. proto3 leaves zero values off the wire, so an OK press is an empty ButtonEvent. The bar has no long-press event.
- Input bursts: during fast input the bar holds input back (up to ~0.75 s) and sends several events in one message, on a steady 1 s beat; detents turned live come one per message. This happens with the physical wheel and with simulated presses, with or without our screen showing. Simulated button presses are held back too, so a message may carry presses and detents together; that is unconfirmed on the bar with the physical wheel and buttons. `decode_input` keeps them in order either way. `State.timestamp` (field 1, ms) is the bar's clock. The wheel's contacts also bounce. `SPEC.md` section 3 covers the bounces, and `decode_input` the held messages.
- Sounds: `stock_path` plays only `shared/...`. The BUSY timer's sounds (`/ext/apps_assets/busy/sounds/*.snd`) must be copied into our assets (`/ext/user_assets/workout-timer/`) and played by `path`. A play request answers 200 even for a missing file: only listening confirms it. The emulator has no such files and beeps for every sound.
- `GET /api/screen?display=0` returns the real LEDs (base64 BGR888); `POST /api/input?key=` presses keys on the real bar.
- busybar-manager treats an exiting app as crashed and restarts it (after 1 s, doubling up to 60 s).

## How to work
1. **Plan before coding.** Read `SPEC.md` and the relevant reference apps, summarise your plan, ask your questions, and wait for the go-ahead.
2. **Small commits**, one logical change each, with a clear message. Run the tests and check the app on the emulator or a bar before committing.
3. **Preserve SPEC.md behaviour.** Ask before changing it, expanding scope, adding dependencies or restructuring the repo.
4. **Verify, don't assume.** If an API detail (inputs, endpoints, audio) isn't confirmed by the bar's API spec or a reference app, say so and propose a test.
5. **Test the logic.** The state machine and controller need unit tests: all three types, pause/resume, early stop, stats, wheel handling.
6. **Look at the output.** Check screens with `tools/screen.py` or `tools/gallery.py`; positions on a 72×16 grid are easy to get wrong.
7. **Hardware:** ask before touching the bar's brightness or other hardware settings (Wi-Fi, firmware, factory reset).
8. Don't commit `reference/`, `.venv/`, `.env` or `config.json`.
