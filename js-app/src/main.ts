// Workout Timer: Tabata, fixed-rest and fixed-work intervals on the BUSY Bar.
// The device layer: input, the 10 Hz loop, HTTP and saved settings. The logic is in the other modules.

import { applySetup, cleanConfig, savedPart, type Config } from "./config.ts";
import { Controller, SOUNDS, type Sound } from "./controller.ts";
import manifest from "./appmeta/manifest.json";
import { changesByItself, render, type Element } from "./render.ts";
import { DrawSchedule } from "./schedule.ts";
import { steadyClock } from "./timer.ts";

const APP = manifest.id;
const API = "http://" + __BUSY_ADDR__ + "/api";
const CONFIG_KEY = "config";
const TICK_MS = 100; // between loop passes: a new second or blink shows this late at most
const PRIORITY = 50; // above built-in apps (10), below a BUSY/CUSTOM session (90)
const SOUND_FILES: Record<Sound, string> = {
  tick: "sounds/countdown_tick.snd",
  finish: "sounds/countdown_finish.snd",
  completed: "sounds/session_completed.snd",
};

// One line per change of problem, not one per retry.
const problems: Record<string, string | null> = {};
function report(kind: string, problem: string | null): void {
  if (problem !== (problems[kind] ?? null)) {
    console.error(APP + ": " + (problem ?? kind + " back"));
    problems[kind] = problem;
  }
}

async function post(path: string, body: object): Promise<Response> {
  const headers = { "Content-Type": "application/json" };
  return fetch(API + path, { method: "POST", headers, body: JSON.stringify(body) });
}

async function draw(elements: Element[]): Promise<boolean> {
  try {
    const answer = await post("/display/draw", { application_name: APP, priority: PRIORITY, elements });
    if (answer.ok) {
      report("display", null);
      return true;
    }
    report("display", answer.status === 409 ? "another app owns the display; waiting" : "draw refused: HTTP " + answer.status);
  } catch (err) {
    report("display", "draw failed: " + String(err));
  }
  return false;
}

function loadConfig(): Config {
  try {
    return cleanConfig(JSON.parse(localStorage.getItem(CONFIG_KEY) ?? "null"));
  } catch {
    return cleanConfig(null);
  }
}

// Setup is on the bar's page for a closed app, so reading these once per run is enough.
async function readSetup(cfg: Config): Promise<void> {
  try {
    const answer = await fetch(API + "/apps/settings?app_id=" + APP);
    if (answer.ok) applySetup(cfg, ((await answer.json()) as { values?: unknown }).values);
    report("setup", answer.ok ? null : "setup settings refused: HTTP " + answer.status);
  } catch (err) {
    report("setup", "setup settings failed: " + String(err));
  }
}

function main(): void {
  const clock = steadyClock(() => Date.now()); // no monotonic clock on the device
  const ctrl = new Controller(loadConfig());
  const schedule = new DrawSchedule(draw, clock, () => pass());
  let playing = false;

  function save(): void {
    if (!ctrl.unsaved()) return;
    try {
      // Rewrites the whole store on flash: only ever on a button press, never per detent.
      localStorage.setItem(CONFIG_KEY, JSON.stringify(savedPart(ctrl.cfg)));
      report("settings", null);
      ctrl.saved();
    } catch (err) {
      report("settings", "cannot save settings: " + String(err));
      ctrl.saveDue = false; // tried; again on the next press and on leaving
    }
  }

  async function play(sound: Sound): Promise<void> {
    playing = true;
    try {
      const answer = await post("/audio/play", { application_name: APP, path: SOUND_FILES[sound] });
      report("sound", answer.ok ? null : "sound refused: HTTP " + answer.status);
    } catch (err) {
      report("sound", "sound failed: " + String(err));
    }
    playing = false;
  }

  function playDue(): void {
    if (!ctrl.sounds.length || playing) return;
    // One sound at a time: the most important one due. Dropped while the screen isn't ours.
    if (schedule.onScreen) {
      const best = ctrl.sounds.reduce((a, b) => (SOUNDS.indexOf(b) > SOUNDS.indexOf(a) ? b : a));
      void play(best);
    }
    ctrl.sounds.length = 0;
  }

  function pass(): void {
    if (closing) return;
    const now = clock();
    ctrl.update(now);
    if (ctrl.saveDue) save();
    if (ctrl.quit) {
      close();
      return;
    }
    schedule.draw(now, () => render(ctrl, now), !changesByItself(ctrl));
    playDue();
  }

  // Releasing everything is the exit: the app ends once no timer, listener or fetch is left.
  let closing = false;
  function close(): void {
    closing = true;
    clearInterval(timer);
    save();
    const done = () => setTimeout(unbind, 0); // not from inside the input handler
    fetch(API + "/display/draw?application_name=" + APP, { method: "DELETE" }).then(done, done);
  }

  const timer = setInterval(pass, TICK_MS);
  const unbind = listen("input", (event) => {
    if (closing) return;
    const now = clock();
    if (event.key === "encoder") {
      ctrl.handle(event.delta, now);
    } else {
      // A long BACK force-quits with no further event: this is the last chance to save.
      if (event.action === "press") save();
      if (event.action === "short") ctrl.handle(event.key, now);
      // A short BACK makes the firmware clear our screen and show its own.
      if (event.key === "back" && (event.action === "short" || event.action === "release")) schedule.reclaim(now);
    }
    schedule.touch();
    pass();
  });
  void readSetup(ctrl.cfg);
  pass();
}

main();
