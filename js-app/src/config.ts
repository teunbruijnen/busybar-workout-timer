// Settings: defaults, validation and wheel steps. Pure, no I/O.
// Invalid values fall back one at a time, so a bad value costs one setting, not all.
// Two owners: the type settings are set in the app and kept in localStorage; the four
// general ones are set under the bar's Setup (appmeta/settings.json) and only read here.

import { FIX_REST, FIX_WORK, TABATA, type Kind, type Rounds } from "./timer.ts";

export const TYPES: readonly Kind[] = [TABATA, FIX_REST, FIX_WORK];
const TIME_MIN = 1; // saved; the wheel's lowest is the time step
const TIME_MAX = 59 * 60 + 59;
const ROUNDS_MAX = 99;
const GET_READY_MAX = 15;
export const STEPS: readonly number[] = [1, 5, 10, 15];
export type SkipButton = "ok" | "start";
export const SKIP_BUTTONS: readonly SkipButton[] = ["ok", "start"];

export interface TypeSettings {
  work: number;
  rest: number;
  rounds: Rounds;
}

export interface Config {
  last_type: Kind;
  types: Record<Kind, TypeSettings>;
  get_ready: number;
  sound: boolean;
  step: number;
  skip_with: SkipButton;
}

export function defaultConfig(): Config {
  return {
    last_type: TABATA,
    types: {
      [TABATA]: { work: 20, rest: 10, rounds: 8 },
      [FIX_REST]: { work: 20, rest: 90, rounds: 5 },
      [FIX_WORK]: { work: 45, rest: 10, rounds: 5 },
    },
    get_ready: 5,
    sound: true,
    step: 5,
    skip_with: "ok",
  };
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function inRange(v: unknown, low: number, high: number): v is number {
  return Number.isInteger(v) && (v as number) >= low && (v as number) <= high;
}

export function cleanConfig(raw: unknown): Config {
  const cfg = defaultConfig();
  if (!isRecord(raw)) return cfg;
  if (TYPES.includes(raw.last_type as Kind)) cfg.last_type = raw.last_type as Kind;
  const types = isRecord(raw.types) ? raw.types : {};
  for (const kind of TYPES) {
    const saved = isRecord(types[kind]) ? types[kind] : {};
    if (inRange(saved.work, TIME_MIN, TIME_MAX)) cfg.types[kind].work = saved.work;
    if (inRange(saved.rest, TIME_MIN, TIME_MAX)) cfg.types[kind].rest = saved.rest;
    if (saved.rounds === null || inRange(saved.rounds, 1, ROUNDS_MAX)) {
      cfg.types[kind].rounds = saved.rounds;
    }
  }
  applyGeneral(cfg, raw);
  return cfg;
}

function applyGeneral(cfg: Config, raw: Record<string, unknown>): void {
  if (inRange(raw.get_ready, 0, GET_READY_MAX)) cfg.get_ready = raw.get_ready;
  if (typeof raw.sound === "boolean") cfg.sound = raw.sound;
  if (STEPS.includes(raw.step as number)) cfg.step = raw.step as number;
  if (SKIP_BUTTONS.includes(raw.skip_with as SkipButton)) cfg.skip_with = raw.skip_with as SkipButton;
}

/** The values of the bar's Setup page, into `cfg`. An enum there is a string: STEP arrives as "5". */
export function applySetup(cfg: Config, values: unknown): void {
  if (!isRecord(values)) return;
  applyGeneral(cfg, { ...values, step: Number(values.step) });
}

/** What the app itself saves. Only these changing is worth a flash write. */
export function savedPart(cfg: Config): Pick<Config, "last_type" | "types"> {
  return { last_type: cfg.last_type, types: cfg.types };
}

/** `i` wrapped into 0..n-1. */
export function wrap(i: number, n: number): number {
  return ((i % n) + n) % n;
}

export function stepMinutes(value: number, delta: number, step: number): number {
  const m = wrap(Math.floor(value / 60) + delta, 60);
  // The lowest time, when a detent lands on 0.
  const s = value % 60;
  return m * 60 + (m === 0 ? Math.max(s, step) : s);
}

export function stepSeconds(value: number, delta: number, step: number): number {
  const m = Math.floor(value / 60);
  let s = value % 60;
  const top = 60 - step;
  const low = m === 0 ? step : 0;
  if (delta > 0) {
    s = (Math.floor(s / step) + 1) * step;
    if (s > top) s = low;
  } else {
    const down = Math.floor((s - 1) / step) * step;
    if (down >= low) s = down;
    else s = s === low ? top : low; // below the step (0:03): up to it
  }
  return m * 60 + s;
}

export function stepRounds(value: Rounds, delta: number): Rounds {
  const i = value === null ? ROUNDS_MAX : value - 1; // 1..99, then unlimited
  const next = wrap(i + delta, ROUNDS_MAX + 1);
  return next === ROUNDS_MAX ? null : next + 1;
}
