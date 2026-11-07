// The menu flow and buttons: pure, no I/O. Wheel turns change `cfg` at once; `saveDue`
// waits for the next button press, so a spin doesn't save once per detent.

import {
  savedPart,
  stepMinutes,
  stepRounds,
  stepSeconds,
  TYPES,
  wrap,
  type Config,
  type TypeSettings,
} from "./config.ts";
import { FIX_REST, FIX_WORK, TABATA, Workout, type Kind, type Phase } from "./timer.ts";

const TYPE_FIELDS: Record<Kind, readonly Field[]> = {
  [TABATA]: ["work", "rest", "rounds"],
  [FIX_REST]: ["rest", "rounds"],
  [FIX_WORK]: ["work", "rounds"],
};
export type Field = "type" | "work" | "rest" | "rounds";
export type TimeField = "work" | "rest";
export const MINUTES = "minutes";
export const SECONDS = "seconds";
export type Part = typeof MINUTES | typeof SECONDS;
export const MENU = "menu";
export const SUMMARY = "summary";
export const RUN = "run";
export const RECAP = "recap";
export type Screen = typeof MENU | typeof SUMMARY | typeof RUN | typeof RECAP;
export type Button = "ok" | "back" | "start";
export type RecapPage = "work" | "rest" | "rounds" | "total";
export const RECAP_PAGES: readonly RecapPage[] = ["work", "rest", "rounds", "total"];
export type Sound = "tick" | "finish" | "completed";
export const SOUNDS: readonly Sound[] = ["tick", "finish", "completed"]; // least to most important
export const FINAL_SECONDS = 3; // the last seconds of a fixed phase tick and blink

const STOP_CONFIRM = 3; // s a STOP? prompt waits for the second BACK
const RECAP_CYCLE = 3; // s per recap page while it pages by itself
const RECAP_GRACE = 1; // s the recap ignores OK and START: a late skip press
const BOUNCE_MS = 80; // one detent turned back sooner is a contact bounce

export function isTimeField(field: Field): field is TimeField {
  return field === "work" || field === "rest";
}

export class Controller {
  cfg: Config;
  screen: Screen = MENU;
  field: Field = "type";
  part: Part = MINUTES;
  choice: Kind; // highlighted on the TYPE wheel
  workout: Workout | null = null;
  stopUntil: number | null = null;
  page: RecapPage | null = null; // recap page; null while it auto-cycles
  inputAt = 0; // the blink of a time being set counts from here
  afterDetent = false; // the last input was a detent: lit for DETENT_LIT
  sounds: Sound[] = [];
  saveDue = false;
  quit = false; // BACK on TYPE: main() closes the app
  private lastDetentAt: number | null = null;
  private lastDetentWay = 0;
  private heardPhase: Phase | null = null;
  private heardRound = 0;
  private heardSeconds: number | null = null;
  private heardAny = false;
  private savedAs: string;

  constructor(cfg: Config) {
    this.cfg = cfg;
    this.choice = cfg.last_type;
    this.savedAs = JSON.stringify(savedPart(cfg));
  }

  get kind(): Kind {
    return this.cfg.last_type;
  }

  unsaved(): boolean {
    return JSON.stringify(savedPart(this.cfg)) !== this.savedAs;
  }

  saved(): void {
    this.savedAs = JSON.stringify(savedPart(this.cfg));
    this.saveDue = false;
  }

  update(now: number): void {
    if (this.stopUntil !== null && now >= this.stopUntil) this.stopUntil = null;
    if (this.screen === RUN) {
      const w = this.workout as Workout;
      w.update(now);
      this.listen(now);
      if (!w.running) {
        // A pending STOP? stays, so its second BACK doesn't skip past the recap.
        this.screen = RECAP;
        this.page = null;
      }
    }
  }

  recapPage(now: number): RecapPage {
    if (this.page !== null) return this.page;
    const shown = Math.floor(this.sinceTheEnd(now) / RECAP_CYCLE);
    return RECAP_PAGES[shown % RECAP_PAGES.length];
  }

  /** One input: a button pressed, or a detent as +1 or -1. */
  handle(event: Button | number, now: number): void {
    this.update(now);
    if (!(this.screen === MENU && event === "start")) {
      this.inputAt = now; // START does nothing in the menu
      this.afterDetent = typeof event === "number";
    }
    if (typeof event === "number") {
      if (this.screen === MENU) this.wheel(event, now);
      else if (this.screen === RECAP) this.turnPage(event, now);
      return;
    }
    this.lastDetentAt = null; // a button ends a turn
    this.lastDetentWay = 0;
    if (this.screen === MENU) this.menu(event);
    else if (this.screen === SUMMARY) this.summary(event, now);
    else if (this.screen === RUN) this.run(event, now);
    else this.recap(event, now);
    this.update(now);
    if (this.unsaved()) this.saveDue = true;
  }

  private menu(button: Button): void {
    if (button === "start") return;
    const field = this.field;
    if (field === "type") {
      if (button === "back") {
        this.quit = true;
      } else {
        this.cfg.last_type = this.choice;
        this.field = TYPE_FIELDS[this.choice][0];
        this.part = MINUTES;
      }
      return;
    }
    if (isTimeField(field)) {
      if (button === "ok" && this.part === MINUTES) {
        this.part = SECONDS;
        return;
      }
      if (button === "back" && this.part === SECONDS) {
        this.part = MINUTES;
        return;
      }
    }
    const fields: readonly Field[] = ["type", ...TYPE_FIELDS[this.kind]];
    const i = fields.indexOf(field) + (button === "ok" ? 1 : -1);
    if (i < fields.length && fields[i] !== "type") {
      this.field = fields[i];
      this.part = button === "ok" ? MINUTES : SECONDS;
    } else if (button === "ok") {
      this.screen = SUMMARY;
    } else {
      this.field = "type";
      this.choice = this.kind;
    }
  }

  private summary(button: Button, now: number): void {
    if (button === "start") {
      this.start(now);
    } else if (button === "back") {
      const fields = TYPE_FIELDS[this.kind];
      this.screen = MENU;
      this.field = fields[fields.length - 1];
    }
  }

  private run(button: Button, now: number): void {
    const w = this.workout as Workout;
    if (button === "back") {
      if (this.stopUntil !== null) {
        this.stopUntil = null; // answered: nothing left pending on the recap
        w.stop(now);
      } else {
        this.stopUntil = now + STOP_CONFIRM;
      }
      return;
    }
    this.stopUntil = null; // any other button answers "no"
    if (button === this.cfg.skip_with) w.advance(now);
    else w.togglePause(now);
  }

  private recap(button: Button, now: number): void {
    const pending = this.stopUntil;
    this.stopUntil = null;
    if (button === "back" && pending !== null) return; // STOP? answered after the end anyway
    if (button !== "back" && this.sinceTheEnd(now) < RECAP_GRACE) return; // a late skip or pause
    if (button === "start") {
      this.start(now);
    } else if (button === "back") {
      this.screen = MENU;
      this.field = "type";
      this.choice = this.kind;
    } else {
      this.turnPage(1, now);
    }
  }

  private turnPage(delta: number, now: number): void {
    const i = RECAP_PAGES.indexOf(this.recapPage(now)) + delta;
    this.page = RECAP_PAGES[wrap(i, RECAP_PAGES.length)];
  }

  private sinceTheEnd(now: number): number {
    // DONE began at exactly the end time, however late update() noticed.
    return now - (this.workout as Workout).phaseStart;
  }

  private start(now: number): void {
    const s = this.settings();
    this.workout = new Workout(this.kind, s.work, s.rest, s.rounds, this.cfg.get_ready);
    this.workout.start(now);
    this.screen = RUN;
    this.stopUntil = null;
    this.heardAny = false;
  }

  private settings(): TypeSettings {
    return this.cfg.types[this.kind];
  }

  /** Queue the sound for what the workout just did. A start is silent unless its first phase is short enough to tick. */
  private listen(now: number): void {
    const w = this.workout as Workout;
    const seconds = w.running ? w.displaySeconds(now) : null;
    const samePhase = !this.heardAny || (w.phase === this.heardPhase && w.round === this.heardRound);
    const lastSeconds = this.heardAny ? this.heardSeconds : null;
    this.heardPhase = w.phase;
    this.heardRound = w.round;
    this.heardSeconds = seconds;
    this.heardAny = true;
    if (samePhase && seconds === lastSeconds) return;
    if (!w.running) {
      // Stopping is the only way an unlimited workout ends: it completes.
      if (!w.stopped || (w.rounds === null && w.round > 0)) this.cue("completed");
    } else if (!samePhase) {
      this.cue("finish");
    } else if (w.isFixed() && !w.paused && (seconds as number) >= 1 && (seconds as number) <= FINAL_SECONDS) {
      this.cue("tick");
    }
  }

  private cue(sound: Sound): void {
    if (this.cfg.sound) this.sounds.push(sound);
  }

  private wheel(delta: number, now: number): void {
    const way = delta > 0 ? 1 : -1;
    if (
      way !== this.lastDetentWay &&
      this.lastDetentAt !== null &&
      now >= this.lastDetentAt &&
      Math.round((now - this.lastDetentAt) * 1000) < BOUNCE_MS
    ) {
      return;
    }
    this.lastDetentAt = now;
    this.lastDetentWay = way;
    const s = this.settings();
    const field = this.field;
    if (isTimeField(field)) {
      const move = this.part === MINUTES ? stepMinutes : stepSeconds;
      s[field] = move(s[field], delta, this.cfg.step);
    } else if (field === "type") {
      this.choice = TYPES[wrap(TYPES.indexOf(this.choice) + delta, TYPES.length)];
    } else {
      s.rounds = stepRounds(s.rounds, delta);
    }
  }
}
