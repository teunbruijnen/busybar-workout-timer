# BUSY Bar Workout Timer: Spec (v1.0)

## 1. Overview

An interval workout timer for the BUSY Bar. The user picks a timer type, sets work time, rest time and rounds in a menu on the bar, runs the workout on the bar's front LED matrix (72×16), and gets a recap at the end.

It runs on the bar itself as a JavaScript app, started from the bar's APPS menu, with no computer attached.

### Goals (v1)
- Three timer types (section 2), each with only the settings that make sense for it.
- Setup entirely on the bar (buttons and wheel); no phone or PC interaction once the app is running.
- Readable at a glance from 1–2 m: big digits, colour-coded phases.
- A recap at the end: time worked, time rested, rounds completed, total time.
- Runs on stock firmware, with no firmware change.

### Non-goals (v1)
- No workout history across sessions (only the last-used settings are kept).
- No phone app, cloud sync, or heart-rate integration.

Ideas for later are in section 9.

---

## 2. Timer types

A workout is a sequence of **rounds**. Each round is a WORK phase followed by a REST phase. Before round 1 comes an optional get-ready phase. A phase is either:
- **fixed:** counts down from a set time and ends by itself, or
- **open:** counts up like a stopwatch and ends when the user skips it.

The get-ready phase is always fixed. The user can skip any phase, ending it at once (section 5.1).

| Type | WORK phase | REST phase | Settings the user chooses |
|---|---|---|---|
| **Tabata** | fixed | fixed | work time, rest time, rounds |
| **Fixed rest** | open | fixed | rest time, rounds |
| **Fixed work** | fixed | open | work time, rounds |

Typical uses: *Tabata* for classic intervals (e.g. 20 s / 10 s × 8). *Fixed rest* for sets of unknown length (reps to failure) with a fixed recovery. *Fixed work* for timed efforts with recovery until ready.

### Rules
- **Get-ready:** before round 1, a countdown of 0–15 s (default 5 s; 0 = off), set under Setup (section 4).
- **No trailing rest:** the workout ends as soon as the final round's WORK phase ends. The last REST is left out.
- **Open phases** have no limit, but the display stops at `+99:59` and stays there until skipped. The stats still count the real time.
- **Rounds:** 1–99, or **unlimited** (`∞` in the menu), for all three types. An unlimited workout repeats WORK and REST until the user stops it (section 5.4).
- **Counting direction is visible:** count-up times have a leading `+` (`+0:23`); count-down times have none.

### Settings ranges and defaults
| Setting | Range | Step | Default |
|---|---|---|---|
| Work time (fixed) | time step – 59:55 with a 5 s step (below) | minutes: 1 min; seconds: the time step; both wrap (below) | 0:20 (Fixed work: 0:45) |
| Rest time (fixed) | time step – 59:55 with a 5 s step | minutes: 1 min; seconds: the time step; both wrap | 0:10 (Fixed rest: 1:30) |
| Rounds | 1 – 99, unlimited | 1; wraps: … 2, 1, ∞, 99, 98 … | 8 (Fixed rest, Fixed work: 5) |
| Get ready | 0 – 15 s (0 = off) | on the Setup page | 5 s |
| Sound | on / off | on the Setup page | on |
| Time step | 1 / 5 / 10 / 15 s | on the Setup page | 5 s |
| Skip with | OK / START | on the Setup page | OK |

A work or rest time is set in two parts (section 4). The minutes run 0–59, one per detent, and wrap around: down from 0 is 59, up from 59 is 0. The seconds move by the time step and wrap within the minute, leaving the minutes unchanged: with a 5 s step …1:50, 1:55, 1:00, 1:05… and back the other way. The highest seconds value is 60 minus the step, so the highest time is 59:59 with a 1 s step, 59:55 with 5 s, 59:50 with 10 s and 59:45 with 15 s. The lowest time is the time step: at 0 minutes the seconds wrap between the step and the top (0:05 ↔ 0:55 with a 5 s step), and whenever the minutes land on 0, down from 1 or up from 59, seconds below the step become the step (1:00 → 0:05, 59:00 → 0:05).

With a time step above 1 s, the seconds snap to a multiple of the step on their first detent. Turning the minutes never changes the seconds, except to keep the lowest time. So after a change of time step, saved seconds stay as they are until turned: 0:03 set with a 1 s step stays 0:03 after switching to 5 s, and its first seconds detent in either direction moves it to 0:05, the lowest time.

---

## 3. Controls

The firmware calls the app for each input (`listen("input", ...)`). A button acts on its `short` action, sent once after a normal press and release. A long press of OK or START does nothing; a long press of BACK is the firmware's force-quit and never reaches the app. A button's `press` only saves pending settings, and BACK's `short` and `release` also take the screen back (section 6, hardware notes). The wheel sends one event per detent.

| Input | Menu | Summary | Workout | Recap |
|---|---|---|---|---|
| **Wheel** | change the value | nothing | nothing | step through the pages |
| **OK** | confirm, go to the next field (WORK, REST: from the minutes to the seconds first) | nothing | skip: end the phase (section 5.1); ignored while paused | next page (not within 1 s of the end) |
| **START** | nothing | start the workout | pause / resume | start the same workout again (not within 1 s of the end, see Recap) |
| **BACK** | previous step (WORK, REST: from the seconds to the minutes; into a time: its seconds); on TYPE: closes the app | back to ROUNDS | STOP? prompt (section 5.4) | back to TYPE |

The table shows the default buttons. **SKIP WITH** (under Setup) set to `START` swaps OK and START during a workout, STOP? prompt included: START skips, OK pauses and resumes. The menu, summary and recap keep the buttons in the table.

**Closing the app:** BACK on TYPE. The app saves any pending settings, removes what it drew and releases its timer and listener, and the bar shows the app's Start / Setup page. A long press of BACK force-quits from any screen; settings are saved on that press, so nothing is lost.

### Turning the wheel in the menu

Every detent moves the value exactly one step (section 2), in every field. Nothing speeds up when the wheel is spun.

The wheel's contacts can bounce. In the menu, a detent against the direction of turning, less than 80 ms after the previous detent, is a contact bounce and is ignored; a button press ends a turn.

**In the recap**, each detent moves one page.

---

## 4. Configuration flow

```
TYPE -> WORK* -> REST* -> ROUNDS -> summary -> (START) -> workout
```
`*` only when the type uses it (section 2): Tabata shows both, Fixed rest skips WORK, Fixed work skips REST. Tabata with 1 round still asks for REST and shows it in the summary (`20/10 x1`), although no REST runs (no trailing rest).

1. **TYPE:** the wheel cycles `TABATA` / `FIXED REST` / `FIXED WORK`, wrapping around. On launch, the last-used type is selected. OK confirms.
2. **WORK:** the work time (`m:ss`), set in two parts. Reached with OK, the minutes blink first and the wheel sets them. OK moves on to the seconds of the same time, which then blink and are set by the wheel. OK on the seconds confirms the time; BACK on the seconds returns to the minutes. Steps and ranges are in section 2.
3. **REST:** the same for the rest time.
4. **ROUNDS:** the wheel sets the number; below 1 is `∞` (unlimited), and the value wraps around. OK confirms.
5. **Summary:** the type name, a START note, and one line with the settings:
   - Tabata: both times, as plain seconds while both are under a minute (`20/10 x8`), otherwise as `m:ss` (`1:30/0:45 x12`).
   - Fixed rest: only the rest time (`1:30 x5`). Fixed work: only the work time (`0:45 x5`). Always `m:ss`, since a lone `90` would be unclear.
   - Unlimited: `x∞` (`20/10 x∞`).

   START begins the workout. BACK returns to ROUNDS. OK and the wheel do nothing.

BACK on ROUNDS, or on the minutes of WORK or REST, goes back one step: into the previous time on its seconds (in Tabata: REST seconds → REST minutes → WORK seconds → WORK minutes), or from the first field after TYPE to TYPE, with the current type selected.

### Setup
GET READY, SOUND, TIME STEP and SKIP WITH are not in the app. They are on the bar's own Setup page for the app, next to Start, which the firmware builds from `appmeta/settings.json`. The app reads them once when it starts, and never writes them. Setup can only be reached with the app closed. Ranges and defaults are in section 2; what SKIP WITH does is in section 3.

### Saved settings
The app keeps:
- the work time, rest time and rounds for **each** timer type, so Tabata keeps its values after a Fixed rest workout. Each type stores both times, including the one it doesn't use (Fixed rest's work time, Fixed work's rest time); those are never shown or used.
- the last-used type, selected on launch.

They are kept on the bar, in the app's `localStorage`, which survives an update, an uninstall and a reinstall of the app. Settings from the Python app are not carried over.

Rules:
- A missing or corrupt value gives the defaults, one value at a time: a single bad value doesn't reset the rest.
- Settings are written on the next button press after a change (not on every detent), and when the app closes. Each write rewrites the store on flash. A failed write is reported, then retried on the next press and on closing.

---

## 5. Workout run

### 5.1 Flow
```
menu -> summary -> GET READY -> WORK <-> REST -> recap -> menu (BACK) or GET READY (START)
```
- Get-ready is left out when set to 0; the workout then starts with WORK.
- A fixed phase ends by itself when its countdown reaches zero.
- **Skip:** OK ends the current phase at once, in every timer type and every phase, get-ready included. This is how an open phase ends; a fixed one ends early (cut a rest short, end an effort early). The time spent counts in the stats, and a WORK phase ended early still completes its round. Ignored while paused; resume first. A skip within 0.5 s after a phase began by itself (its time ran out) is ignored, pauses excluded: a press meant for the phase that just ended doesn't skip the next one. A phase begun by a skip has no such grace, so skipping twice in a row works.
- The final round's WORK leads straight to the recap. With unlimited rounds there is no final round; the workout only ends when stopped (5.4).
- **Pause:** START pauses and resumes any phase. Paused, the phase is frozen and resumes exactly where it left off. BACK still raises the STOP? prompt.
- **Swapped buttons:** with SKIP WITH set to `START`, START skips and OK pauses and resumes (section 3).

### 5.2 Timing rules
- Time comes from the bar's clock (`Date.now()`, the only clock an app has), never from counting timer ticks. A reading that goes back, or forward by more than 10 s, counts as no time at all, so a time sync in the middle of a workout doesn't move it; a real stall that long costs the workout that much time. Smaller forward jumps pass as time. A fixed phase ends exactly at its start plus its duration, however late the app notices; slow draws, refused draws and lost connections never make the timer drift or stop.
- Paused time counts toward neither work nor rest.
- Button presses are handled as soon as they arrive. The screen is checked about 10 times a second, but redrawn only when what it shows changes: the displayed second, the phase, the state, a menu value, or a blink (section 6), plus a periodic refresh (section 8). The progress bar steps once per displayed second, so it never causes extra redraws.

### 5.3 Statistics
- **Work time:** time spent in WORK phases (for open phases, their real duration).
- **Rest time:** time spent in REST phases.
- **Rounds completed:** WORK phases that ended (by themselves or skipped).
- **Total time:** from the first WORK start to the end, excluding pauses and get-ready. Phases follow each other without gaps, so this is work time plus rest time.

Blinking never adds or removes time.

### 5.4 Ending early
BACK during a workout shows `STOP?` in place of the label. A second BACK within 3 s confirms; otherwise the prompt disappears and the workout carries on. The timer never stops while the prompt is up. OK or START while `STOP?` is up answer "no": the prompt goes away and the button does its workout job, skip or pause as SKIP WITH assigns them (a skip is still ignored while paused, or within its grace, section 5.1).

A confirmed stop goes to the recap with the partial stats:
- Time already spent in the interrupted WORK or REST phase counts toward work or rest time and total time. Stopped while paused, it counts up to the moment of pausing.
- A WORK phase cut short by the stop does **not** count as a completed round. A round stopped during its REST has already counted.
- Stopped during get-ready, all stats are zero.

The recap is labelled `STOPPED` (red) after every confirmed stop, including a stop of an unlimited workout. Separately, an unlimited workout stopped after its first WORK has begun plays the completed sound, since stopping is the only way it ends (section 7). Label and sound don't conflict: the label says how the workout ended, the sound marks the end of the session.

If the workout ends by itself while `STOP?` is up, the recap appears. A BACK in what is left of those 3 s is ignored, so the intended confirmation doesn't skip past the recap. Any other button cancels the pending prompt and does its recap job (START and OK within 1 s of the end are still ignored). After a stop confirmed with BACK BACK nothing is pending: BACK on the recap returns to TYPE at once.

---

## 6. Display design (72×16 front LED matrix)

### Colours
| What | Colour |
|---|---|
| WORK: label, time, progress bar; the WORK label in the menu and recap; the summary's START note | green `#00FF40FF` |
| REST: label, time, progress bar; the REST label in the menu and recap | amber `#FFA000FF` |
| Get-ready: label, time, progress bar | blue `#3090FFFF` |
| Paused: label, round counter, time, progress bar | grey `#808080FF` |
| `STOP?` label, `STOPPED` note | red `#FF3030FF` |
| Round counter; all other menu, summary and recap labels | light grey `#C0C0C0FF` |
| Menu and summary values | white `#FFFFFFFF` |
| Recap values, `DONE` note | cyan `#00E0FFFF` |
| Progress bar track | the bar's colour at 20% brightness |

The menu shows one field at a time, so nothing is highlighted.

### Workout screens
```
 WORK     0:23      3/8          fixed phase
 ########################

 WORK    +0:23      3/8          open phase: no progress bar

 READY      5                    get-ready: plain seconds, no round counter
 ########################

 PAUSE    0:23      3/8          paused: all grey, the time blinks
 ########################
```
Measured layout:
```
 columns 0-24, small font               columns 26-66, extra_large, colon on x=49
 rows 0-4    label   WORK / REST / READY / PAUSE / STOP?
 rows 6-12   round   3/8, or R12 when unlimited; none during get-ready.
             bold while no wider than the label WORK (3/8, R12), else condensed (12/99, R100)
                                         rows 2-11  time   0:23 · +0:23 · 5 (get-ready) · max +99:59
 row 15      progress bar, fixed phases (get-ready included): full width
```
- **Times** are `m:ss` during a workout, with minutes going past 59 (up to `99:59`). Get-ready shows plain seconds. `h:mm:ss` is only used for recap totals.
- **The time stands still**, like a digital clock: every digit has a cell as wide as a 0 (in `extra_large` a 1 is 3 px narrower and sits in the middle of its cell), and the colon is always on column 49. The minutes end at the colon and the seconds start after it, so the colon, the seconds and the last minute digit hold still between phases and as the minutes change width. At `+10:00` only the `+` moves, one cell further out to make room. A time like `0:20` sits right of the middle of the time area: columns 41-66, with 5 blank columns to its right. Get-ready has no colon: its seconds are right-aligned in a box as wide as its start, centred on x=49. `+99:59` keeps a blank column beside the widest label and counter.
- **Progress bar** (fixed phases, get-ready included): shows the time left, over a dim track the full width of row 15. It is full at the start, and each displayed second removes 1/N of it for an N-second phase (a 20 s phase loses 1/20 per second; widths are rounded up to whole columns). It changes only when the displayed second changes.
- **Last 3 seconds of a fixed phase** (get-ready included): only the last digit blinks. It shows for the first 0.5 s of each second and is hidden for the rest, in step with the ticks (section 7).
- **Paused:** everything turns grey and the whole time blinks, 0.5 s on, 0.5 s off, starting visible.
- **STOP?** replaces the label in red; the rest of the screen keeps running.
- **No skip hint in open phases** (neither a tiny "OK" nor a corner mark reads well). The `+` and the missing progress bar set them apart.

### Menu and summary
```
 TYPE   TABATA          (one field per screen: label small, value large)
 WORK    0:20
 ROUNDS  ∞
```
Measured layout:
```
 rows 0-4    label, small, top left: TYPE / WORK (green) / REST (amber) / ROUNDS
             summary: the timer type name
 top right   summary only: START in tiny green letters, flush right, its top row level with the label's
 rows 6-15   value, extra_large, centred: TABATA · FIXED REST · FIXED WORK · 8 · ∞; a time keeps its colon on column 32: 0:20
             summary line: extra_large if it fits, else condensed on rows 7-13
```
- Times and rounds use the same fixed digit cells as the workout, so they don't shift as the wheel turns.
- WORK and REST keep their colon on column 32, so `0:20` and `59:20` differ only in the minutes. `m:ss` is 1 px off the middle of the bar and `mm:ss` 3 px. The recap stays centred: it doesn't tick, and its pages hold different figures.
- On WORK and REST the part being set, minutes or seconds, blinks like the paused time (0.5 s on, 0.5 s off); the colon and the other part stay lit. The blink starts as soon as the part is reached (OK or BACK): 0.5 s lit, then 0.5 s off. After a wheel detent it stays lit for 1 s, so the value can be read while the wheel turns; then it blinks, starting with 0.5 s off.
- The widest summary (`59:59/59:59 x99`) is 70 px in `condensed`, so the summary never needs to scroll.
- No type name on the WORK, REST and ROUNDS screens (`FIXED WORK` ran into `ROUNDS`).

### Recap
```
 WORK   6:40
 REST   3:20
 ROUNDS 8/8      (unlimited: ROUNDS 7)
 TOTAL 10:00     (from an hour on: h:mm:ss, e.g. 1:15:00)
```
Measured layout:
```
 rows 0-4    page label, small, top left: WORK (green) / REST (amber) / ROUNDS / TOTAL
 top right   tiny, flush right, top row level with the label's: DONE (cyan) when the workout ran to its end, STOPPED (red) when stopped
 rows 6-15   value, extra_large, cyan, centred: 2:40 · 8/8 (unlimited: 41) · 1:42:05
```
- Pages run WORK → REST → ROUNDS → TOTAL, 3 s each, counted from the moment the workout ended, and keep cycling until OK or the wheel is used. The first OK or wheel turn steps on from the page on screen and stops the cycling for good; both wrap around. START repeats the same workout. Within 1 s of the workout ending, START and OK are ignored, so a late or doubled press of the skip button on the last phase doesn't restart the workout or turn the page. BACK returns to TYPE with that workout's type selected.
- Times are whole seconds, rounded down, as during the workout. Each page rounds on its own, so WORK + REST can show one second less than TOTAL when phases end mid-second (an open phase, or a skip).
- No page dots: the value fills rows 6-15, and the label says which page it is.
- The widest value, a total of 10 hours or more (`10:00:05`), is 49 px in `extra_large`.

### General rules
- Text is printable ASCII (the bar's fonts and API accept nothing else). `∞` is pixel art: 16×10 beside `extra_large` digits, 9×5 centred on `condensed` digits.
- Text that doesn't fit must scroll or be abbreviated, never be clipped or run into other text.
- Every screen looks pixel-identical on the bar and in the emulator (checked on firmware 1.2.4). The app positions everything itself rather than relying on the bar's centring, which rounds differently from the emulator.
- Every element carries a fixed stacking order, so overlapping elements always layer the same way.

### Hardware notes (firmware 1.3.1, API 27.14.0)
- **BACK:** a short BACK makes the firmware remove the app's screen and show its own "Loading...", whatever the draw priority, while the app keeps running. An app can't prevent this. On BACK's `short` and `release` the app re-sends its visible elements back to back for 0.4 s; the wipes wait until after. "Loading..." shows for about 175 ms after a press (measured with simulated keys).
- **Other buttons:** OK, START and the wheel reach only the app.
- **Input:** events arrive one at a time. Ten simulated detents sent as fast as possible arrived about 20 ms apart, with none held back. A physical fast spin hasn't been measured.
- **Draw cost:** a draw of 1-2 elements takes 20-50 ms, a full 26 elements 90-160 ms, so the app sends only what changed and keeps one draw in flight. A new screen and the wipes of the old one go in one draw, the wipes first, because the bar can show the state between a draw's elements: this way two screens don't show on top of each other, though a part-drawn screen can show for 35 ms at most.

---

## 7. Audio

The app uses the BUSY timer's own sounds (those of the bar's pomodoro timer):
- **Tick** (0.25 s): counts down the last 3 seconds of every fixed phase (get-ready included) to the end of that phase, as 3, 2, 1 appear, in step with the blinking digit. Not while paused, and not in open phases (they count up).
- **Finish** (0.19 s): every phase change, by itself or skipped.
- **Completed** (2.3 s): a workout that ends by itself or by a skip of its last phase. A stopped workout ends in silence, with one exception: an unlimited workout stopped after its first WORK has begun plays it. A stop during get-ready is always silent.

Rules:
- Only one sound plays at a time. When several are due at once, only the most important plays: completed, then finish, then tick. So a phase of 3 s or less, entered from another phase, starts with the finish sound instead of its first tick; its remaining seconds tick.
- Starting a workout makes no sound of its own. If the first phase (get-ready, or the first WORK when get-ready is off) is fixed and 3 s or shorter, its countdown ticks from its very first second. This is intended: the ticks count down to the end of the phase, not the start of the workout.
- Sound on/off is set under Setup. The bar's own volume applies.
- Sound never affects the timer. A failed sound is reported once. Whenever the last draw failed (refused, e.g. because another app owns the display; section 8), due sounds are dropped instead of sent. Later sounds play again once drawing works.

**Getting the sounds onto the bar.** The bar plays only its shared stock sounds by name, and an app can't reach the BUSY timer's sound files. So the three sounds are packaged in the app and played from its `sounds/` folder. They are the firmware's own files, under CC BY-SA 4.0, kept in `js-app/src/sounds` with a notice in `js-app/src/resources/NOTICE.txt`.

---

## 8. Running

### Platform
- A JavaScript app for the firmware's JerryScript runtime, written in TypeScript, in `js-app/`. App id `app.teunbruijnen.workout_timer`. It needs API 27.12.0 or newer and has been run on 27.14.0 (firmware 1.3.1).
- It talks to the bar only through `http://localhost/api`: `display/draw` and `audio/play`. Input comes through `listen`.

### Drawing
- Only elements that changed are sent, one draw at a time; changes made meanwhile go out when it settles. Every 5 s the whole visible screen is sent again; this renews the elements' timeout and takes the screen back after a refusal.
- Elements expire 15 s after they were last sent, so a dead app doesn't leave a frozen timer on the bar.
- After a failed draw, nothing is sent for 1 s; then the whole screen is sent again. Until a draw succeeds, due sounds are dropped (section 7).
- Draw priority is 50: above built-in apps (10), below an active BUSY or CUSTOM work session (90). A BUSY session started during a workout closes the app (firmware 1.3.1). When another app holds the screen, draws are refused (HTTP 409) and the timer keeps running unseen.
- Problems (another app owns the display, draw refused, sound failed, settings not saved, Setup values not read) are logged once per change of state.

### Differences from the Python app
- It runs on the bar, so there is no `--host`, `--token` or `--test`, no busybar-manager, and no connection to lose.
- BACK on TYPE closes the app, where `app.py` ignores it because the manager would restart an app that exits.
- Buttons act on `short`, on release, where `app.py` acts on the press.
- No held-burst handling. Sounds ship with the app; settings live on the bar.
- No SETTINGS on the TYPE wheel: the four general settings are on the bar's Setup page. `js-app/tools/oracle.py` and `tools/jscheck.py` take SETTINGS off `app.py`'s wheel to compare.

---

## 9. Out of scope / later
- Multi-exercise programmes (e.g. "pushups, then squats").
- A warm-up phase, or a long rest between blocks of rounds.
