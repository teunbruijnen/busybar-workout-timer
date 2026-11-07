// The workout state machine: pure, no I/O. Time is in seconds on one clock, passed in.
// A fixed phase ends at exactly start + duration, however late update() runs.

export const TABATA = "tabata";
export const FIX_REST = "fix_rest";
export const FIX_WORK = "fix_work";
export type Kind = typeof TABATA | typeof FIX_REST | typeof FIX_WORK;

export const GET_READY = "get_ready";
export const WORK = "work";
export const REST = "rest";
export const DONE = "done";
export type Phase = typeof GET_READY | typeof WORK | typeof REST | typeof DONE;

export type Rounds = number | null; // null = unlimited

const OPEN_CAP = 99 * 60 + 59; // an open phase's display stops here (99:59)
const MAX_CLOCK_STEP = 10; // s; more than this in one reading is a time sync, not time passing
const SKIP_GRACE = 0.5; // s a phase that began by itself ignores skips meant for the last one

/**
 * Seconds since the first call, from a wall clock that a time sync can move. A step back, or
 * forward by more than MAX_CLOCK_STEP, counts as nothing: the workout carries on from where
 * it was. A real stall that long costs the workout that much time, which beats running through
 * every phase of the jump at once.
 */
export function steadyClock(wall: () => number): () => number {
  let last = wall();
  let elapsed = 0;
  return () => {
    const now = wall();
    const step = now - last;
    last = now;
    if (step > 0 && step <= MAX_CLOCK_STEP * 1000) elapsed += step;
    return elapsed / 1000;
  };
}

export class Workout {
  kind: Kind;
  work: number;
  rest: number;
  rounds: Rounds;
  getReady: number;
  phase: Phase | null = null;
  round = 0;
  phaseStart = 0; // shifted forward by pauses
  beganByItself = false;
  pausedAt: number | null = null;
  stopped = false;
  workSeconds = 0;
  restSeconds = 0;
  roundsCompleted = 0;

  constructor(kind: Kind, work: number, rest: number, rounds: Rounds, getReady: number) {
    this.kind = kind;
    this.work = work;
    this.rest = rest;
    this.rounds = rounds;
    this.getReady = getReady;
  }

  // Phases follow each other without gaps; get-ready and pauses don't count.
  get totalSeconds(): number {
    return this.workSeconds + this.restSeconds;
  }

  get paused(): boolean {
    return this.pausedAt !== null;
  }

  get running(): boolean {
    return this.phase === GET_READY || this.phase === WORK || this.phase === REST;
  }

  isFixed(): boolean {
    if (this.phase === GET_READY) return true;
    if (this.phase === WORK) return this.kind !== FIX_REST;
    if (this.phase === REST) return this.kind !== FIX_WORK;
    return false;
  }

  duration(): number {
    if (this.phase === GET_READY) return this.getReady;
    return this.phase === WORK ? this.work : this.rest;
  }

  elapsed(now: number): number {
    if (!this.running) return 0;
    const clock = this.pausedAt !== null ? this.pausedAt : now;
    return Math.max(0, clock - this.phaseStart);
  }

  displaySeconds(now: number): number {
    const elapsed = this.elapsed(now);
    if (this.isFixed()) {
      // Rounded up: a 20 s phase shows 20 first and 1 last.
      return Math.max(0, Math.ceil(this.duration() - elapsed - 1e-9));
    }
    return Math.min(OPEN_CAP, Math.trunc(elapsed));
  }

  start(now: number): void {
    if (this.getReady > 0) this.enter(GET_READY, now);
    else this.beginWork(now);
  }

  update(now: number): void {
    while (this.running && !this.paused && this.isFixed()) {
      const end = this.phaseStart + this.duration();
      if (now < end) break;
      this.finishPhase(end, true);
    }
  }

  /** Skip the current phase. Ignored while paused, and within SKIP_GRACE of a phase that began by itself. */
  advance(now: number): void {
    this.update(now);
    if (this.running && !this.paused && !this.inSkipGrace(now)) this.finishPhase(now, false);
  }

  togglePause(now: number): void {
    this.update(now);
    if (!this.running) return;
    if (this.pausedAt !== null) {
      this.phaseStart += now - this.pausedAt;
      this.pausedAt = null;
    } else {
      this.pausedAt = now;
    }
  }

  stop(now: number): void {
    this.update(now);
    if (!this.running) return;
    this.bank(this.elapsed(now));
    this.stopped = true;
    this.pausedAt = null;
    this.enter(DONE, now);
  }

  private enter(phase: Phase, at: number): void {
    this.phase = phase;
    this.phaseStart = at;
  }

  private beginWork(at: number): void {
    this.round += 1;
    this.enter(WORK, at);
  }

  private bank(seconds: number): void {
    if (this.phase === WORK) this.workSeconds += seconds;
    else if (this.phase === REST) this.restSeconds += seconds;
  }

  private inSkipGrace(now: number): boolean {
    return this.beganByItself && this.elapsed(now) < SKIP_GRACE;
  }

  private finishPhase(end: number, byItself: boolean): void {
    this.bank(end - this.phaseStart);
    this.beganByItself = byItself;
    if (this.phase === WORK) {
      this.roundsCompleted += 1;
      if (this.rounds !== null && this.round >= this.rounds) {
        this.enter(DONE, end); // no trailing rest
      } else {
        this.enter(REST, end);
      }
    } else {
      this.beginWork(end);
    }
  }
}
