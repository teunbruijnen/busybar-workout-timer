// When the app draws, and what it sends. Only what changed goes out; all visible elements
// go out every REFRESH s, renewing their timeouts and taking the screen back after a 409,
// and back to back for RECLAIM s just after BACK. At most one draw is in flight: changes made
// meanwhile go out once it settles. After a failed draw nothing is sent for RETRY s.
// No I/O of its own: `send` and `clock` come in from main(), so tests drive it with fakes.

import { Painter, type Element } from "./render.ts";

const REFRESH = 5; // s between redraws of an unchanged frame, renewing its timeout
const RETRY = 1; // s before retrying a failed draw; after a 409, it retakes the screen
const RECLAIM = 0.4; // s of full draws after BACK, each starting when the last one settles: the firmware may clear us just after one, and its "Loading..." stays until the next

export class DrawSchedule {
  /** Did the last draw that finished succeed? Sounds wait on it. */
  onScreen = true;
  private send: (elements: Element[]) => Promise<boolean>;
  private clock: () => number;
  private settled: () => void;
  private painter = new Painter();
  private holdUntil = 0;
  private nextFull = 0;
  private reclaimUntil = 0;
  private upToDate = false; // the bar shows, or is being sent, the last frame built
  private sending = false;

  constructor(send: (elements: Element[]) => Promise<boolean>, clock: () => number, settled: () => void) {
    this.send = send;
    this.clock = clock;
    this.settled = settled;
  }

  /** Something on screen changed: an input. */
  touch(): void {
    this.upToDate = false;
  }

  /** BACK: the firmware also takes a short BACK press, clears our elements and shows "Loading...". Drawing takes the screen back, so send the visible elements at once and again for a moment. */
  reclaim(now: number): void {
    this.forget();
    this.nextFull = now;
    this.reclaimUntil = now + RECLAIM;
  }

  /** One pass: send what changed in the frame `build` makes. `steady` says it can't have changed by time alone; then, unless a full draw is due, it isn't even built. */
  draw(now: number, build: () => Element[], steady: boolean): void {
    if (this.sending || now < this.holdUntil) return;
    // Bounded both ways: whatever the clock does, this must not run on for longer than RECLAIM.
    const reclaiming = now < this.reclaimUntil && this.reclaimUntil - now <= RECLAIM;
    const full = reclaiming || now >= this.nextFull;
    if (!full && steady && this.upToDate) return;
    const [first, later] = this.painter.plan(build(), full);
    this.upToDate = true;
    // The wipes wait out a reclaim: a draw of only blanks would leave the screen empty.
    if (full) this.nextFull = reclaiming ? this.reclaimUntil : now + REFRESH;
    const wipes = reclaiming ? [] : later;
    if (first.length || wipes.length) {
      this.sending = true;
      void this.sendAll(first, wipes);
    }
  }

  private async sendAll(first: Element[], later: Element[]): Promise<void> {
    let ok = true;
    if (first.length) {
      ok = await this.send(first);
      if (ok) this.painter.sent(first);
    }
    // An input arrived meanwhile: show it first. These wipes stay due, for the next pass.
    if (ok && later.length && this.upToDate) {
      ok = await this.send(later);
      if (ok) this.painter.sent(later);
    }
    this.sending = false;
    this.onScreen = ok;
    if (!ok) {
      this.forget();
      // From now, not from the pass's start: a draw that timed out has already taken a while.
      this.holdUntil = this.nextFull = this.clock() + RETRY;
    }
    this.settled();
  }

  private forget(): void {
    this.painter.forget();
    this.upToDate = false;
  }
}
