// Does the port behave like the Python app? tools/oracle.py runs ../app.py through seeded
// random sessions; this replays the same inputs here and compares every step.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import { cleanConfig, stepMinutes, stepRounds, stepSeconds } from "../src/config.ts";
import { Controller } from "../src/controller.ts";
import { changesByItself, fmtTime, Painter, render, textWidth } from "../src/render.ts";

const SESSIONS = "300";
const STEPS = "150";
const lines = execFileSync("python3", [new URL("../tools/oracle.py", import.meta.url).pathname, SESSIONS, STEPS], {
  encoding: "utf8",
  maxBuffer: 1 << 30,
})
  .trim()
  .split("\n")
  .map((line) => JSON.parse(line));

const table = (key: string) => lines.find((line) => key in line)[key];

function sortKeys(value: any): any {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(Object.keys(value).sort().map((k) => [k, sortKeys(value[k])]));
}

const isBlank = (e: any) => (e.type === "text" ? !e.text.trim() : e.x >= 72 || e.y >= 16);

test("wheel steps", () => {
  const fns: any = { step_minutes: stepMinutes, step_seconds: stepSeconds };
  for (const [fn, value, delta, step, want] of table("steps")) {
    assert.equal(fns[fn](value, delta, step), want, `${fn}(${value}, ${delta}, ${step})`);
  }
  for (const [value, delta, want] of table("rounds")) assert.equal(stepRounds(value, delta), want);
});

test("time formats and text widths", () => {
  for (const [value, plus, hours, want] of table("times")) assert.equal(fmtTime(value, plus, hours), want);
  let printable = "";
  for (let c = 32; c < 127; c++) printable += String.fromCharCode(c);
  for (const [font, want] of table("widths")) assert.equal(textWidth(printable, font), want, font);
});

test("config validation", () => {
  for (const [raw, want] of table("configs")) {
    assert.deepEqual(sortKeys(cleanConfig(raw)), sortKeys(want), JSON.stringify(raw));
  }
});

test("random sessions: state, frames, sounds and draw plans match the Python app", () => {
  let ctrl: Controller | null = null;
  let painter = new Painter();
  let session = -1;
  const shown = new Set<string>();
  const heard = new Set<string>();
  let steps = 0;
  for (const line of lines) {
    if ("session" in line) {
      session = line.session;
      ctrl = new Controller(cleanConfig(line.cfg));
      painter = new Painter();
      continue;
    }
    if (!("t" in line)) continue;
    const c = ctrl as Controller;
    const now = line.t / 1000;
    const where = `session ${session}, t=${line.t}, event ${line.event}`;
    if (line.event === null) c.update(now);
    else c.handle(line.event, now);

    const w = c.workout;
    assert.deepEqual(
      {
        screen: c.screen,
        field: c.field,
        part: c.part,
        choice: c.choice,
        page: c.screen === "recap" ? c.recapPage(now) : null,
        stop_until: c.stopUntil,
        save_due: c.saveDue,
        by_itself: changesByItself(c),
        sounds: c.sounds,
        workout: w && {
          phase: w.phase,
          round: w.round,
          paused: w.paused,
          work: w.workSeconds,
          rest: w.restSeconds,
          done: w.roundsCompleted,
          stopped: w.stopped,
        },
      },
      {
        screen: line.screen,
        field: line.field,
        part: line.part,
        choice: line.choice,
        page: line.page,
        stop_until: line.stop_until,
        save_due: line.save_due,
        by_itself: line.by_itself,
        sounds: line.sounds,
        workout: line.workout,
      },
      where,
    );
    assert.deepEqual(sortKeys(c.cfg), sortKeys(line.cfg), where);

    const elements = render(c, now);
    assert.equal(elements.length, 29, where);
    const compared = line.elements.length === 29 ? elements : elements.filter((e) => !isBlank(e));
    assert.deepEqual(sortKeys(compared), sortKeys(line.elements), where);

    if (line.forget) painter.forget();
    // The same elements as the Python app, split differently: see Painter.plan.
    const [first, later] = painter.plan(elements, line.refresh);
    painter.sent([...first, ...later]);
    const ids = [...first, ...later].map((e) => e.id).sort();
    assert.deepEqual(ids, [...line.visible, ...line.wipes].sort(), where);

    for (const e of elements) if (e.type === "text" && e.text.trim()) shown.add(e.text);
    for (const s of c.sounds) heard.add(s);
    c.sounds.length = 0;
    if (c.saveDue) c.saved();
    steps++;
  }
  assert.equal(steps, Number(SESSIONS) * Number(STEPS));

  // The sessions must have reached what they claim to check.
  for (const text of ["TYPE", "WORK", "REST", "ROUNDS", "READY", "PAUSE",
    "STOP?", "TOTAL", "DONE", "STOPPED", "START", "TABATA", "FIXED REST", "FIXED WORK"]) {
    assert.ok(shown.has(text), "never shown: " + text);
  }
  assert.ok([...shown].some((t) => /^\d+:\d\d:\d\d$/.test(t)), "never shown: h:mm:ss");
  assert.ok([...shown].some((t) => /^R\d+$/.test(t)), "never shown: an unlimited round");
  assert.ok([...shown].some((t) => /^\d+\/\d+ x/.test(t)), "never shown: a summary");
  for (const sound of ["tick", "finish", "completed"]) assert.ok(heard.has(sound), "never heard: " + sound);
});
