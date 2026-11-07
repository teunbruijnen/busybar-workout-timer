// What is new in the port, so the Python app can't be the reference for it.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { applySetup, cleanConfig, defaultConfig, savedPart, SKIP_BUTTONS, STEPS } from "../src/config.ts";
import { Controller } from "../src/controller.ts";
import { fmtTime, Painter, type Element } from "../src/render.ts";
import { DrawSchedule } from "../src/schedule.ts";
import { steadyClock, Workout } from "../src/timer.ts";

test("BACK on TYPE closes the app; BACK elsewhere doesn't", () => {
  const ctrl = new Controller(defaultConfig());
  ctrl.handle("ok", 1); // TABATA -> WORK
  ctrl.handle("back", 2); // WORK -> TYPE
  assert.equal(ctrl.field, "type");
  assert.equal(ctrl.quit, false);
  ctrl.handle("back", 3);
  assert.equal(ctrl.quit, true);
});

test("the TYPE wheel holds the three types, wrapping", () => {
  const ctrl = new Controller(defaultConfig());
  ctrl.handle(-1, 1);
  assert.equal(ctrl.choice, "fix_work");
  ctrl.handle(1, 2);
  assert.equal(ctrl.choice, "tabata");
});

// --- the bar's Setup page: appmeta/settings.json

const schema = JSON.parse(readFileSync(new URL("../src/appmeta/settings.json", import.meta.url), "utf8"));

test("the Setup schema's defaults are the app's defaults", () => {
  const cfg = cleanConfig(null);
  const values = Object.fromEntries(Object.entries(schema.fields).map(([id, f]: [string, any]) => [id, f.default]));
  const fromSchema = defaultConfig();
  fromSchema.get_ready = fromSchema.sound = fromSchema.step = fromSchema.skip_with = undefined as any;
  applySetup(fromSchema, values);
  assert.deepEqual(fromSchema, cfg);
});

test("every Setup option is a value the app accepts", () => {
  for (const { value } of schema.fields.step.options) {
    const cfg = defaultConfig();
    cfg.step = 0;
    applySetup(cfg, { step: value });
    assert.equal(cfg.step, Number(value));
  }
  for (const { value } of schema.fields.skip_with.options) {
    const cfg = defaultConfig();
    applySetup(cfg, { skip_with: value });
    assert.equal(cfg.skip_with, value);
  }
  assert.deepEqual(schema.fields.step.options.map((o: any) => Number(o.value)), STEPS, "and all of them are offered");
  assert.deepEqual(schema.fields.skip_with.options.map((o: any) => o.value), SKIP_BUTTONS);
  assert.equal(schema.fields.get_ready.min, 0);
  assert.equal(schema.fields.get_ready.max, 15);
});

test("a bad Setup value costs that one setting only; no values, nothing", () => {
  const cfg = defaultConfig();
  applySetup(cfg, { get_ready: 99, sound: "no", step: "7", skip_with: "start" });
  assert.deepEqual(cfg, { ...defaultConfig(), skip_with: "start" });
  for (const nothing of [undefined, null, 3, []]) {
    const same = defaultConfig();
    applySetup(same, nothing);
    assert.deepEqual(same, defaultConfig());
  }
});

test("Setup values landing don't cost a flash write, and aren't saved by the app", () => {
  const ctrl = new Controller(defaultConfig());
  applySetup(ctrl.cfg, { get_ready: 2, sound: false, step: "10", skip_with: "start" });
  assert.equal(ctrl.unsaved(), false);
  ctrl.handle("ok", 1);
  ctrl.handle(1, 2); // WORK minutes + 1
  assert.equal(ctrl.unsaved(), true);
  assert.deepEqual(Object.keys(savedPart(ctrl.cfg)).sort(), ["last_type", "types"]);
});

test("a detent turned back within 80 ms is a bounce; after 80 ms, or after a button, it counts", () => {
  const ctrl = new Controller(defaultConfig());
  ctrl.handle("ok", 1);
  ctrl.handle("ok", 2);
  ctrl.handle("ok", 3); // WORK minutes, WORK seconds, now REST minutes
  const rest = ctrl.cfg.types.tabata.rest;
  ctrl.handle(1, 10); // minutes +1
  assert.equal(ctrl.cfg.types.tabata.rest, rest + 60);
  ctrl.handle(-1, 10.05); // a bounce
  assert.equal(ctrl.cfg.types.tabata.rest, rest + 60);
  ctrl.handle(-1, 10.13); // past 80 ms: a real turn back
  assert.equal(ctrl.cfg.types.tabata.rest, rest);
});

// --- the draw schedule: a fake bar that answers when told to ---

function el(id: string, text: string): Element {
  return { id, type: "text", text, x: 0, y: 0, font: "small", color: "#FFFFFFFF", timeout: 15 };
}

test("a new screen and the wipes of the old one go in one draw, wipes first, so they don't show on top of each other", () => {
  const painter = new Painter();
  const blank = (id: string): Element => ({ ...el(id, " "), font: "tiny", color: "#00000000" });
  const [first, later] = painter.plan([el("label", "TYPE"), el("value", "TABATA"), blank("c0")], false);
  assert.deepEqual(first.map((e) => e.id), ["label", "value"]);
  assert.deepEqual(later.map((e) => e.id), ["c0"], "maybe lit: wiped after");
  painter.sent([...first, ...later]);
  // Frame order has the label first and the digits last; the wipe of the value still leads.
  const [next, nothing] = painter.plan([el("label", "WORK"), blank("value"), el("c0", "0")], false);
  assert.deepEqual(next.map((e) => e.id), ["value", "label", "c0"]);
  assert.deepEqual(nothing, []);
});

function setup() {
  const sent: Element[][] = [];
  let answer: (ok: boolean) => void = () => {};
  let now = 0;
  let settled = 0;
  const schedule = new DrawSchedule(
    (elements) => {
      sent.push(elements);
      return new Promise((resolve) => (answer = resolve));
    },
    () => now,
    () => settled++,
  );
  const reply = async (ok: boolean) => {
    answer(ok);
    await new Promise((resolve) => setImmediate(resolve));
  };
  return { sent, schedule, reply, setNow: (t: number) => (now = t), settledCount: () => settled };
}

test("one draw in flight: changes wait, then only the latest goes out", async () => {
  const { sent, schedule, reply } = setup();
  schedule.draw(0, () => [el("a", "1")], true);
  schedule.touch();
  schedule.draw(0.1, () => [el("a", "2")], true);
  schedule.draw(0.2, () => [el("a", "3")], true);
  assert.equal(sent.length, 1, "nothing queues while a draw is out");
  await reply(true);
  schedule.draw(0.3, () => [el("a", "4")], true);
  assert.deepEqual(sent.map((p) => (p[0] as any).text), ["1", "4"]);
});

test("an input during a draw isn't lost: touch() forces the next frame", async () => {
  const { sent, schedule, reply } = setup();
  schedule.draw(0, () => [el("a", "1")], true);
  schedule.touch();
  await reply(true);
  schedule.draw(0.1, () => [el("a", "2")], true);
  assert.equal(sent.length, 2);
});

test("a steady screen with nothing new isn't rebuilt; an unchanged one sends nothing", async () => {
  const { sent, schedule, reply } = setup();
  let built = 0;
  const build = () => {
    built++;
    return [el("a", "1")];
  };
  schedule.draw(0, build, true);
  await reply(true);
  schedule.draw(0.1, build, true);
  assert.equal(built, 1);
  schedule.draw(0.2, build, false);
  assert.equal(built, 2);
  assert.equal(sent.length, 1);
});

test("all visible elements go out again every 5 s", async () => {
  const { sent, schedule, reply } = setup();
  schedule.draw(0, () => [el("a", "1")], true);
  await reply(true);
  schedule.draw(4.9, () => [el("a", "1")], true);
  assert.equal(sent.length, 1);
  schedule.draw(5, () => [el("a", "1")], true);
  assert.equal(sent.length, 2);
});

test("a failed draw: nothing for 1 s, then the whole frame; sounds wait on it", async () => {
  const { sent, schedule, reply, setNow } = setup();
  schedule.draw(0, () => [el("a", "1")], true);
  setNow(0.5);
  await reply(false);
  assert.equal(schedule.onScreen, false);
  schedule.draw(1.4, () => [el("a", "1")], false);
  assert.equal(sent.length, 1, "still holding off");
  schedule.draw(1.5, () => [el("a", "1")], false);
  assert.equal(sent.length, 2);
  await reply(true);
  assert.equal(schedule.onScreen, true);
});

test("BACK: the whole frame back to back for 0.4 s, then one more, then every 5 s", async () => {
  const { sent, schedule, reply } = setup();
  schedule.draw(0, () => [el("a", "1")], true);
  await reply(true);
  const draws = async (t: number) => {
    const before = sent.length;
    schedule.draw(t, () => [el("a", "1")], true);
    if (sent.length > before) await reply(true);
    return sent.length - before;
  };
  schedule.reclaim(2);
  assert.equal(await draws(2), 1);
  assert.equal(await draws(2.01), 1, "no gap: the next starts when the last one settles");
  assert.equal(await draws(2.39), 1);
  assert.equal(await draws(2.4), 1, "the one that clears what waited out the reclaim");
  assert.equal(await draws(2.5), 0, "the 5 s pace again");
  assert.equal(await draws(7.4), 1);
});

test("BACK: the wipes wait until it ends: a draw of only blanks leaves the screen empty", async () => {
  const { sent, schedule, reply } = setup();
  const blank: Element = { ...el("label", " "), font: "tiny", color: "#00000000" };
  const build = () => [blank, el("a", "1")];
  schedule.draw(0, build, true);
  await reply(true);
  await reply(true); // the first wipes: the slot is known to be blank now
  sent.length = 0;
  schedule.reclaim(2); // and now it isn't known any more
  schedule.draw(2, build, true);
  assert.deepEqual(sent.at(-1)?.map((e) => e.id), ["a"]);
  await reply(true);
  assert.equal(sent.length, 1, "no wipes after it");
  schedule.draw(2.2, build, true);
  assert.deepEqual(sent.at(-1)?.map((e) => e.id), ["a"]);
  await reply(true);
  schedule.draw(2.4, build, true);
  assert.deepEqual(sent.at(-1)?.map((e) => e.id), ["a"]);
  await reply(true);
  assert.deepEqual(sent.at(-1)?.map((e) => e.id), ["label"], "over: now they go");
  await reply(true);
});

test("BACK, then the clock jumps back: no back-to-back draws for the length of the jump", async () => {
  const { sent, schedule, reply } = setup();
  schedule.draw(0, () => [el("a", "1")], true);
  await reply(true);
  schedule.reclaim(100);
  schedule.draw(50, () => [el("a", "1")], true);
  assert.equal(sent.length, 2, "once: BACK left the screen unknown");
  await reply(true);
  schedule.draw(50.01, () => [el("a", "1")], true);
  assert.equal(sent.length, 2, "then nothing: the frame is unchanged and no full draw is due");
});

test("an input during the visible draw goes ahead of the wipes, which stay due", async () => {
  const { sent, schedule, reply } = setup();
  const label: Element = { ...el("label", " "), font: "tiny", color: "#00000000" };
  schedule.draw(0, () => [label, el("value", "1")], true);
  schedule.touch();
  await reply(true);
  assert.equal(sent.length, 1, "no wipes yet");
  schedule.draw(0.1, () => [label, el("value", "2")], true);
  assert.deepEqual(sent[1].map((e) => e.id), ["value"]);
  await reply(true);
  assert.deepEqual(sent[2].map((e) => e.id), ["label"]);
});

test("the visible elements go before the wipes", async () => {
  const { sent, schedule, reply } = setup();
  const blank: Element = { ...el("b", " "), font: "tiny", color: "#00000000" };
  const unknownSlot: Element = { ...el("label", " "), font: "tiny", color: "#00000000" };
  schedule.draw(0, () => [blank, unknownSlot, el("value", "1")], true);
  assert.deepEqual(sent[0].map((e) => e.id), ["value"]);
  await reply(true);
  assert.deepEqual(sent[1].map((e) => e.id), ["label"]);
});

function fakeWall(start: number) {
  const wall = { ms: start, read: () => wall.ms };
  return wall;
}

test("the clock counts normal steps from zero", () => {
  const wall = fakeWall(5000);
  const clock = steadyClock(wall.read);
  assert.equal(clock(), 0);
  wall.ms += 100;
  assert.equal(clock(), 0.1);
  wall.ms += 10000; // the most it trusts
  assert.equal(clock(), 10.1);
});

test("a time sync moves the wall clock, not the workout's clock", () => {
  const wall = fakeWall(5000);
  const clock = steadyClock(wall.read);
  wall.ms += 1000;
  assert.equal(clock(), 1);
  wall.ms += 86400000; // forward a day
  assert.equal(clock(), 1);
  wall.ms += 100;
  assert.equal(clock(), 1.1);
  wall.ms -= 86400000; // back a day
  assert.equal(clock(), 1.1);
  wall.ms += 100;
  assert.equal(clock(), 1.2);
  wall.ms += 10001; // just over
  assert.equal(clock(), 1.2);
});

test("a jump in the wall clock leaves a running workout in its phase", () => {
  const wall = fakeWall(1700000000000);
  const clock = steadyClock(wall.read);
  const workout = new Workout("tabata", 20, 10, 8, 0);
  workout.start(clock());
  wall.ms += 5000;
  workout.update(clock());
  wall.ms += 86400000;
  workout.update(clock());
  assert.equal(workout.phase, "work");
  assert.equal(workout.round, 1);
});

test("a recap's time doesn't lose a second to rounding when phases are added up, whenever the workout starts", () => {
  for (let ms = 0; ms < 60000; ms += 7) {
    const start = ms / 1000;
    const w = new Workout("tabata", 5, 5, 2, 2);
    w.start(start);
    w.update(start + 17.5);
    assert.equal(fmtTime(w.workSeconds), "0:10", "started at " + start);
    assert.equal(fmtTime(w.totalSeconds), "0:15", "started at " + start);
  }
});
