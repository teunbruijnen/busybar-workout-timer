// Display elements for every screen: pure, no I/O. The app positions everything itself:
// the bar's `align` rounds differently from the emulator.

import type { Config } from "./config.ts";
import {
  Controller,
  FINAL_SECONDS,
  isTimeField,
  MENU,
  MINUTES,
  RECAP,
  RUN,
  SECONDS,
  SUMMARY,
  type Field,
  type Part,
  type RecapPage,
} from "./controller.ts";
import { FIX_REST, FIX_WORK, GET_READY, TABATA, WORK, type Kind, type Workout } from "./timer.ts";

export const W = 72;
export const H = 16;
const ELEMENT_TIMEOUT = 15; // s; a dead app doesn't leave a frozen timer behind

interface TextElement {
  id: string;
  type: "text";
  text: string;
  x: number;
  y: number;
  font: string;
  color: string;
  timeout: number;
  z_index?: number;
}

interface RectElement {
  id: string;
  type: "rectangle";
  x: number;
  y: number;
  width: number;
  height: number;
  fill: "solid";
  fill_colors: string[];
  border_width: number;
  timeout: number;
  z_index?: number;
}

export type Element = TextElement | RectElement;
type Parts = Record<string, Element>;

// Text is printable ASCII only, so the infinity sign is drawn from rectangles, one set per
// font (x, y, width, height), generated once from the pixel art in ../app.py.
const INF_RECTS: Record<string, number[][]> = {
  extra_large: [[2,0,3,1],[11,0,3,1],[1,1,5,1],[10,1,5,1],[0,2,2,6],[5,2,2,1],[9,2,2,1],[14,2,2,6],[6,3,4,1],[7,4,2,2],[6,6,4,1],[5,7,2,1],[9,7,2,1],[1,8,5,1],[10,8,5,1],[2,9,3,1],[11,9,3,1]],
  condensed: [[1,0,2,1],[6,0,2,1],[0,1,1,3],[3,1,1,1],[5,1,1,1],[8,1,1,3],[4,2,1,1],[3,3,1,1],[5,3,1,1],[1,4,2,1],[6,4,2,1]],
};
const INF_SIZE: Record<string, number[]> = {"extra_large": [16, 10], "condensed": [9, 5]};
const INF_SLOTS = Array.from({ length: 17 }, (_, i) => "inf" + i);

// Every frame fills the same ids, back to front. Each id keeps one type: the bar answers
// 400 to a text id turned into a rectangle or back.
const CLOCK_SLOTS = ["c0", "c1", "c2", "c3", "c4", "c5"]; // from the right: c0 is the last digit
const PART_SLOTS: Record<Part, string[]> = {
  [SECONDS]: CLOCK_SLOTS.slice(0, 2),
  [MINUTES]: CLOCK_SLOTS.slice(3), // c2 is the colon of m:ss
};
const TEXT_SLOTS = ["label", "round", "note", "value", ...CLOCK_SLOTS];
const RECT_SLOTS = [...INF_SLOTS, "bar_bg", "bar"];
const SLOTS = [...TEXT_SLOTS, ...RECT_SLOTS];

const COLOR_WORK = "#00FF40FF";
const COLOR_REST = "#FFA000FF";
const COLOR_READY = "#3090FFFF";
const COLOR_PAUSED = "#808080FF"; // dimmed by colour: the emulator ignores alpha on text
const COLOR_STOP = "#FF3030FF";
const COLOR_LABEL = "#C0C0C0FF";
const COLOR_VALUE = "#FFFFFFFF";
const COLOR_RECAP = "#00E0FFFF";

const TYPE_NAMES: Record<Kind, string> = {
  [TABATA]: "TABATA",
  [FIX_REST]: "FIXED REST",
  [FIX_WORK]: "FIXED WORK",
};
const FIELD_LABELS: Record<Field | RecapPage, string> = {
  type: "TYPE",
  work: "WORK",
  rest: "REST",
  rounds: "ROUNDS",
  total: "TOTAL",
};

function labelColor(field: Field | RecapPage): string {
  if (field === "work") return COLOR_WORK;
  return field === "rest" ? COLOR_REST : COLOR_LABEL;
}

const BLINK = 0.5; // s on, then s off
const DETENT_LIT = 1; // s lit after a detent, so the value can be read while the wheel turns

// A text element's y is its font box, which has blank rows above the ink.
const INK_TOP: Record<string, number> = { tiny: 1, small: 2, condensed: 2, bold: 2, extra_large: 2 };
const INK_ROWS: Record<string, number> = { condensed: 7, extra_large: 10 }; // digit height
const TIME_MID_X = 49; // the time's colon, and the middle of a get-ready: +99:59 keeps a blank column beside PAUSE and 99/99
const MENU_COLON_X = 32; // the menu's colon: m:ss is 1 px off the middle of the bar, mm:ss 3 px
const ROW_LABEL = 0;
const ROW_ROUND = 6;
const ROW_TIME = 2;
const ROW_VALUE = 6; // menu value: extra_large ink on rows 6-15
const BAR_ROW = H - 1;

// Glyph advances for " " to "~" as chr(32 + px). No glyph draws past its advance, so a
// string's width is their sum.
const ADVANCE: Record<string, string> = {
  tiny: "#\"$&$%%\"##$$\"$\"%$$$$$$$$$$\"\"$$$$$$$$$$$$$$$%$&%%$%$$$%&&$&%#%#$$#$$$$$##$\"\"$\"&$$$$#$$$$&$$$$\"$%",
  small: "\"\"$&$%%\"##$$\"#\"#$#$$$$$$$$\"#$$$$%%%%%%%%%\"$%$&%%%%%%$%$&$$$###$$$$$$$$#$$\"#$\"&$$$$#$#$$&$$$$\"$%",
  condensed: "%#$&&('\"##$&#$$%%%%%%%%%%%\"#$&$&(&&&&&&&&$%&%(&&&&&&&&&(&&&#%#&%&%%%%%%%%$$%$&%%%%$%%%&&&%%$#$&",
  bold: "%$$())(\"$$$'#$$&''''''''''\"#%'%'*''''&&''%&'&*('''''''(+'''$&$'%'&&&&&&&&%%&%(&&&&%&&&'('&&%$%&",
  extra_large: "$#&*)+*#%%''#$#&(%((((((((##%'%',((((''((%'(')(((((('())(('$&$(%'((((''((%'(')(((((('())(('&#&(",
};

export function textWidth(txt: string, font: string): number {
  let width = 0;
  for (let i = 0; i < txt.length; i++) width += ADVANCE[font].charCodeAt(txt.charCodeAt(i) - 32) - 32;
  return width;
}

function text(id: string, txt: string, x: number, y: number, font: string, color: string): TextElement {
  return { id, type: "text", text: txt, x, y, font, color, timeout: ELEMENT_TIMEOUT };
}

function rect(id: string, x: number, y: number, width: number, height: number, color: string): RectElement {
  return {
    id,
    type: "rectangle",
    x,
    y,
    width,
    height,
    fill: "solid",
    fill_colors: [color],
    border_width: 0,
    timeout: ELEMENT_TIMEOUT,
  };
}

// Built once: render() runs ten times a second on a small heap, and most slots are blank.
const BLANKS: Record<string, Element> = {};
SLOTS.forEach((id, z) => {
  const el = RECT_SLOTS.includes(id)
    ? rect(id, W, H, 1, 1, "#00000000") // the bar refuses a zero-size one
    : text(id, " ", 0, 0, "tiny", "#00000000");
  el.z_index = z;
  BLANKS[id] = el;
});

function frame(parts: Parts): Element[] {
  return SLOTS.map((id, z) => {
    const el = parts[id];
    if (!el) return BLANKS[id];
    el.z_index = z;
    return el;
  });
}

function isBlank(el: Element): boolean {
  if (el.type === "text") return !el.text.trim();
  return el.x >= W || el.y >= H;
}

function sameElement(a: Element, b: Element): boolean {
  if (a === b) return true;
  if (a.x !== b.x || a.y !== b.y) return false;
  if (a.type === "text") {
    const t = b as TextElement;
    return a.text === t.text && a.font === t.font && a.color === t.color;
  }
  const r = b as RectElement;
  return a.width === r.width && a.height === r.height && a.fill_colors[0] === r.fill_colors[0];
}

/** The bar keeps each element until it is replaced, so a draw sends only the changes, and a blank only to wipe what may still be shown. */
export class Painter {
  private shown: Record<string, Element> = {};
  private unsure: Record<string, boolean> = {};

  constructor() {
    this.forget();
  }

  /** The bar's state is unknown: start, a failed draw, BACK. */
  forget(): void {
    this.shown = {};
    this.unsure = {};
    for (const id of SLOTS) this.unsure[id] = true;
  }

  /**
   * [now, later]. `now` holds the wipes of what is known to be on screen, then what changed.
   * The bar applies a draw's elements in order and can show the state in between, so the
   * old screen goes first: on a change of screen the other order showed a mix for 80-110 ms,
   * this one nothing or a part-drawn screen for 35 ms at most. `later` holds the wipes of
   * slots that may or may not be lit, after a start, BACK or a failed draw: `now` stays small and
   * fast. A refresh resends everything visible.
   */
  plan(elements: Element[], refresh: boolean): [Element[], Element[]] {
    const wipes: Element[] = [];
    const changes: Element[] = [];
    const later: Element[] = [];
    for (const el of elements) {
      const was = this.shown[el.id];
      if (isBlank(el)) {
        if (was && !sameElement(was, el)) wipes.push(el);
        else if (this.unsure[el.id]) later.push(el);
      } else if (refresh || !was || !sameElement(was, el)) {
        changes.push(el);
      }
    }
    return [[...wipes, ...changes], later];
  }

  sent(elements: Element[]): void {
    for (const el of elements) {
      this.shown[el.id] = el;
      delete this.unsure[el.id];
    }
  }
}

function dim(color: string, factor: number): string {
  let out = "#";
  for (const i of [1, 3, 5]) {
    const c = Math.round(parseInt(color.slice(i, i + 2), 16) * factor);
    out += c.toString(16).toUpperCase().padStart(2, "0");
  }
  return out + "FF";
}

function two(n: number): string {
  return String(n).padStart(2, "0");
}

export function fmtTime(seconds: number, plus = false, hours = false): string {
  const whole = Math.trunc(seconds + 1e-9); // phases added up can land just under a whole second
  const m = Math.floor(whole / 60);
  const s = whole % 60;
  const body = hours && m >= 60 ? Math.floor(m / 60) + ":" + two(m % 60) + ":" + two(s) : m + ":" + two(s);
  return (plus ? "+" : "") + body;
}

function leftText(id: string, txt: string, row: number, color: string, font = "small"): TextElement {
  return text(id, txt, 0, row - INK_TOP[font], font, color);
}

/** Each character's x in extra_large, and the width. Every digit has a cell as wide as a 0 (a 1 is 3 px narrower), so a time doesn't shift as it changes. */
function clockCells(txt: string): [number[], number] {
  const cell = textWidth("0", "extra_large");
  const xs: number[] = [];
  let x = 0;
  for (const ch of txt) {
    if (ch >= "0" && ch <= "9") {
      xs.push(x + Math.floor((cell - textWidth(ch, "extra_large") + 1) / 2));
      x += cell;
    } else {
      xs.push(x);
      x += textWidth(ch, "extra_large");
    }
  }
  return [xs, x];
}

function clock(parts: Parts, txt: string, x: number, top: number, color: string, hide: string[]): void {
  const xs = clockCells(txt)[0];
  for (let i = 0; i < txt.length; i++) {
    const slot = CLOCK_SLOTS[txt.length - 1 - i];
    if (!hide.includes(slot)) {
      parts[slot] = text(slot, txt[i], x + xs[i], top - INK_TOP.extra_large, "extra_large", color);
    }
  }
}

/** An m:ss time with its colon on a fixed column, so nothing moves when the minutes change width: they end at the colon, the seconds start after it. */
function clockOnColon(parts: Parts, txt: string, colonX: number, top: number, color: string, hide: string[]): void {
  clock(parts, txt, colonX - clockCells(txt)[0][txt.indexOf(":")], top, color, hide);
}

function blinkedOff(since: number): boolean {
  return since % (2 * BLINK) >= BLINK;
}

function phaseLabel(w: Workout): string {
  if (w.paused) return "PAUSE";
  if (w.phase === GET_READY) return "READY";
  return w.phase === WORK ? "WORK" : "REST";
}

function phaseColor(w: Workout): string {
  if (w.paused) return COLOR_PAUSED;
  if (w.phase === GET_READY) return COLOR_READY;
  return w.phase === WORK ? COLOR_WORK : COLOR_REST;
}

export function renderWorkout(w: Workout, now: number, confirmStop: boolean): Element[] {
  const fixed = w.isFixed();
  const color = phaseColor(w);
  const parts: Parts = {};

  parts.label = confirmStop
    ? leftText("label", "STOP?", ROW_LABEL, COLOR_STOP)
    : leftText("label", phaseLabel(w), ROW_LABEL, color);
  if (w.phase !== GET_READY) {
    // Bold while no wider than the label, else condensed, which clears the widest time.
    const counter = w.rounds === null ? "R" + w.round : w.round + "/" + w.rounds;
    const font = textWidth(counter, "bold") <= textWidth("WORK", "small") ? "bold" : "condensed";
    parts.round = leftText("round", counter, ROW_ROUND, w.paused ? COLOR_PAUSED : COLOR_LABEL, font);
  }

  const seconds = w.displaySeconds(now);
  const shown = w.phase === GET_READY ? String(seconds) : fmtTime(seconds, !fixed);
  let hideAll = false;
  let hideDigit = false;
  if (w.pausedAt !== null) {
    hideAll = blinkedOff(now - w.pausedAt);
  } else if (fixed && seconds <= FINAL_SECONDS) {
    hideDigit = seconds - (w.duration() - w.elapsed(now)) >= BLINK;
  }
  if (!hideAll) {
    const hide = hideDigit ? CLOCK_SLOTS.slice(0, 1) : [];
    if (w.phase === GET_READY) {
      // Right-aligned in a box as wide as the start, so 10 -> 9 doesn't move.
      const width = clockCells(shown)[1];
      const box = Math.max(width, clockCells(String(w.duration()))[1]);
      clock(parts, shown, TIME_MID_X - Math.floor(box / 2) + box - width, ROW_TIME, color, hide);
    } else {
      clockOnColon(parts, shown, TIME_MID_X, ROW_TIME, color, hide);
    }
  }

  if (fixed) {
    // From the shown seconds, so the bar never needs a draw of its own.
    parts.bar_bg = rect("bar_bg", 0, BAR_ROW, W, 1, dim(color, 0.2));
    const barWidth = Math.ceil((W * seconds) / w.duration());
    if (barWidth > 0) parts.bar = rect("bar", 0, BAR_ROW, barWidth, 1, color);
  }
  return frame(parts);
}

/** `txt` (then the infinity sign if `inf`) centred, in condensed if extra_large doesn't fit, so nothing scrolls. `steady` draws it as a clock, and a time on its colon. */
function valueLine(parts: Parts, txt: string, color: string, inf = false, steady = false, hide: string[] = []): void {
  if (steady && !inf) {
    const top = ROW_VALUE + Math.floor((H - ROW_VALUE - INK_ROWS.extra_large) / 2);
    if (txt.includes(":")) clockOnColon(parts, txt, MENU_COLON_X, top, color, hide);
    else clock(parts, txt, Math.floor((W - clockCells(txt)[1]) / 2), top, color, hide);
    return;
  }
  let font = "extra_large";
  let infWidth = inf ? INF_SIZE[font][0] + (txt ? 1 : 0) : 0;
  let width = textWidth(txt, font) + infWidth;
  if (width > W) {
    font = "condensed";
    infWidth = inf ? INF_SIZE[font][0] + (txt ? 1 : 0) : 0;
    width = textWidth(txt, font) + infWidth;
  }
  const x0 = Math.floor((W - width) / 2);
  const top = ROW_VALUE + Math.floor((H - ROW_VALUE - INK_ROWS[font]) / 2);
  if (txt) parts.value = text("value", txt, x0, top - INK_TOP[font], font, color);
  if (inf) {
    const ix = x0 + width - INF_SIZE[font][0];
    const iy = top + Math.floor((INK_ROWS[font] - INF_SIZE[font][1]) / 2);
    INF_RECTS[font].forEach((r, i) => {
      const slot = INF_SLOTS[i];
      parts[slot] = rect(slot, ix + r[0], iy + r[1], r[2], r[3], color);
    });
  }
}

function corner(txt: string, color: string): TextElement {
  return text("note", txt, W - textWidth(txt, "tiny"), ROW_LABEL - INK_TOP.tiny, "tiny", color);
}

function fieldValue(cfg: Config, field: Field, choice: Kind): [string, boolean] {
  const s = cfg.types[cfg.last_type];
  if (field === "type") return [TYPE_NAMES[choice], false];
  if (isTimeField(field)) return [fmtTime(s[field]), false];
  return s.rounds === null ? ["", true] : [String(s.rounds), false];
}

function renderMenu(cfg: Config, field: Field, choice: Kind, hiddenPart: Part | null): Element[] {
  const parts: Parts = { label: leftText("label", FIELD_LABELS[field], ROW_LABEL, labelColor(field)) };
  const [txt, inf] = fieldValue(cfg, field, choice);
  const hide = hiddenPart && isTimeField(field) ? PART_SLOTS[hiddenPart] : [];
  valueLine(parts, txt, COLOR_VALUE, inf, isTimeField(field) || field === "rounds", hide);
  return frame(parts);
}

function summaryText(kind: Kind, work: number, rest: number): string {
  if (kind === FIX_REST) return fmtTime(rest) + " x";
  if (kind === FIX_WORK) return fmtTime(work) + " x";
  if (work < 60 && rest < 60) return work + "/" + rest + " x";
  return fmtTime(work) + "/" + fmtTime(rest) + " x";
}

function renderSummary(cfg: Config): Element[] {
  const kind = cfg.last_type;
  const s = cfg.types[kind];
  const line = summaryText(kind, s.work, s.rest);
  const parts: Parts = {
    label: leftText("label", TYPE_NAMES[kind], ROW_LABEL, COLOR_LABEL),
    note: corner("START", COLOR_WORK),
  };
  if (s.rounds === null) valueLine(parts, line, COLOR_VALUE, true);
  else valueLine(parts, line + s.rounds, COLOR_VALUE);
  return frame(parts);
}

function recapValue(w: Workout, page: RecapPage): string {
  if (page === "rounds") {
    return w.rounds === null ? String(w.roundsCompleted) : w.roundsCompleted + "/" + w.rounds;
  }
  const seconds = page === "work" ? w.workSeconds : page === "rest" ? w.restSeconds : w.totalSeconds;
  return fmtTime(seconds, false, true);
}

function renderRecap(w: Workout, page: RecapPage): Element[] {
  const parts: Parts = {
    label: leftText("label", FIELD_LABELS[page], ROW_LABEL, labelColor(page)),
    note: w.stopped ? corner("STOPPED", COLOR_STOP) : corner("DONE", COLOR_RECAP),
  };
  valueLine(parts, recapValue(w, page), COLOR_RECAP);
  return frame(parts);
}

export function render(ctrl: Controller, now: number): Element[] {
  if (ctrl.screen === MENU) {
    // After a detent, the blink's first lit half stretches to DETENT_LIT.
    const since = now - ctrl.inputAt - (ctrl.afterDetent ? DETENT_LIT - BLINK : 0);
    const hidden = blinkedOff(Math.max(0, since)) ? ctrl.part : null;
    return renderMenu(ctrl.cfg, ctrl.field, ctrl.choice, hidden);
  }
  if (ctrl.screen === SUMMARY) return renderSummary(ctrl.cfg);
  const w = ctrl.workout as Workout;
  if (ctrl.screen === RECAP) return renderRecap(w, ctrl.recapPage(now));
  return renderWorkout(w, now, ctrl.stopUntil !== null);
}

/** Whether render(ctrl, now) can change with `now` alone. */
export function changesByItself(ctrl: Controller): boolean {
  return (
    ctrl.screen === RUN ||
    (ctrl.screen === RECAP && ctrl.page === null) ||
    (ctrl.screen === MENU && isTimeField(ctrl.field))
  );
}
