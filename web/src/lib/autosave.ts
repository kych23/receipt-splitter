/**
 * Debounced whole-document saves with retry (docs/design/slice-3-manual-split.md, "Save loop").
 *
 * Plain class, no React: the component hook only forwards edits and renders `status`. At most one
 * request is in flight, and every request sends the *current* state, so an edit made while a save
 * is in flight or backing off is never lost.
 */

import {
  ApiError,
  type ReceiptResponse,
  type SaveReceiptRequest,
  type SaveResult,
} from "./api/receipts";
import { type EditorState, toSaveBody } from "./receipt-state";

export const DEBOUNCE_MS = 600;
export const MAX_SERVER_RETRIES = 5;
const NETWORK_BACKOFF_STEPS = 3; // 2, 4, 8 s, then every 30 s
const NETWORK_STEADY_MS = 30_000;

export type SaveStatus =
  | { kind: "idle" }
  | { kind: "invalid"; lineIds: string[] }
  | { kind: "offline" }
  | { kind: "paused" }
  | { kind: "rejected" }
  | { kind: "gave_up" };

type Retry =
  | { kind: "none" }
  | { kind: "backoff"; reason: "server" | "network"; attempt: number }
  | { kind: "gave_up" }
  | { kind: "paused" };

export type AutosaverDeps = {
  receiptId: string;
  save: (
    id: string,
    body: SaveReceiptRequest,
    signal: AbortSignal,
  ) => Promise<SaveResult>;
  /** Make a replacement receipt when the current one has expired or was deleted elsewhere. */
  create: () => Promise<ReceiptResponse>;
  getState: () => EditorState;
  onSaved: (receipt: ReceiptResponse, revision: number) => void;
  onRecreated: (receipt: ReceiptResponse) => void;
  onStatus: (status: SaveStatus) => void;
};

export class Autosaver {
  private id: string;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private inFlight: AbortController | null = null;
  private recreating = false;
  /** Set after a recreate until a save succeeds, so a 404 on the replacement can't loop. */
  private unsavedReplacement = false;
  /** Bumped by cancel() so a replacement that finishes afterwards is ignored. */
  private generation = 0;
  private retry: Retry = { kind: "none" };
  private status: SaveStatus = { kind: "idle" };

  constructor(private readonly deps: AutosaverDeps) {
    this.id = deps.receiptId;
  }

  /** The receipt currently being saved to (changes if it had to be recreated). */
  get receiptId(): string {
    return this.id;
  }

  /** A local edit happened. */
  edited(): void {
    if (this.retry.kind === "paused") return; // the pause ends with one save of the current state
    this.retry = { kind: "none" };
    this.schedule(DEBOUNCE_MS);
  }

  /** The Retry button (shown only after giving up): same as a new edit. */
  retryNow(): void {
    this.unsavedReplacement = false; // one more recreate per click; the user paces any loop
    this.edited();
  }

  /** Cancel timers and abort the in-flight save (unmount, delete, start new). */
  cancel(): void {
    this.clearTimer();
    this.inFlight?.abort();
    this.inFlight = null;
    this.recreating = false;
    this.generation += 1;
    this.retry = { kind: "none" };
  }

  private setStatus(status: SaveStatus): void {
    this.status = status;
    this.deps.onStatus(status);
  }

  private clearTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private schedule(delayMs: number): void {
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.run();
    }, delayMs);
  }

  private async run(): Promise<void> {
    // A save already in flight re-checks the revision when it finishes; a recreate runs a save
    // of the current state when it finishes.
    if (this.inFlight !== null || this.recreating) return;
    const state = this.deps.getState();
    if (!state.dirty) return;

    const prepared = toSaveBody(state);
    if ("invalid" in prepared) {
      this.setStatus({ kind: "invalid", lineIds: prepared.invalid });
      return;
    }
    if (this.status.kind === "invalid" || this.status.kind === "rejected") {
      this.setStatus({ kind: "idle" });
    }

    const revision = state.revision;
    const controller = new AbortController();
    this.inFlight = controller;
    let result: SaveResult;
    try {
      result = await this.deps.save(this.id, prepared.body, controller.signal);
    } catch {
      return; // aborted by cancel(); nothing to update
    } finally {
      if (this.inFlight === controller) this.inFlight = null;
    }
    if (controller.signal.aborted) return;
    this.handle(result, revision);
  }

  private handle(result: SaveResult, revision: number): void {
    const changedSince = () => this.deps.getState().revision !== revision;
    switch (result.kind) {
      case "saved":
        this.unsavedReplacement = false;
        this.retry = { kind: "none" };
        this.setStatus({ kind: "idle" });
        this.deps.onSaved(result.receipt, revision);
        if (changedSince()) this.schedule(DEBOUNCE_MS);
        return;
      case "not_found":
        // The row expired (e.g. never saved within an hour, or offline past the TTL) or was
        // deleted elsewhere. The edits only exist here, so move them to a new receipt — once:
        // a replacement that 404s too means something else is wrong, so stop and offer Retry.
        if (this.unsavedReplacement) {
          this.retry = { kind: "gave_up" };
          this.setStatus({ kind: "gave_up" });
          return;
        }
        void this.recreate();
        return;
      case "rate_limited":
        this.retry = { kind: "paused" };
        this.setStatus({ kind: "paused" });
        this.clearTimer();
        this.timer = setTimeout(() => {
          this.timer = null;
          this.retry = { kind: "none" };
          this.setStatus({ kind: "idle" });
          void this.run();
        }, result.retryAfterS * 1000);
        return;
      case "rejected":
        this.retry = { kind: "none" };
        this.setStatus({ kind: "rejected" });
        if (changedSince()) this.schedule(DEBOUNCE_MS);
        return;
      case "server_error": {
        const attempt = this.nextAttempt("server");
        if (attempt > MAX_SERVER_RETRIES) {
          this.retry = { kind: "gave_up" };
          this.setStatus({ kind: "gave_up" });
          return;
        }
        this.retry = { kind: "backoff", reason: "server", attempt };
        this.schedule(2 ** attempt * 1000);
        return;
      }
      case "network_error": {
        const attempt = this.nextAttempt("network");
        this.retry = { kind: "backoff", reason: "network", attempt };
        this.setStatus({ kind: "offline" });
        this.schedule(
          attempt <= NETWORK_BACKOFF_STEPS
            ? 2 ** attempt * 1000
            : NETWORK_STEADY_MS,
        );
        return;
      }
    }
  }

  private async recreate(): Promise<void> {
    this.clearTimer();
    this.recreating = true;
    const generation = this.generation;
    let receipt: ReceiptResponse;
    try {
      receipt = await this.deps.create();
    } catch (error) {
      if (generation !== this.generation) return;
      this.recreating = false;
      // Each retry re-sends to the old id, gets 404 again, and recreates.
      const revision = this.deps.getState().revision;
      if (error instanceof ApiError && error.status === null) {
        this.handle({ kind: "network_error" }, revision);
      } else if (error instanceof ApiError && error.status === 429) {
        this.handle(
          { kind: "rate_limited", retryAfterS: error.retryAfterS ?? 60 },
          revision,
        );
      } else {
        this.retry = { kind: "gave_up" };
        this.setStatus({ kind: "gave_up" });
      }
      return;
    }
    if (generation !== this.generation) return;
    this.recreating = false;
    this.unsavedReplacement = true;
    this.id = receipt.id;
    this.retry = { kind: "none" }; // backoff from the old receipt doesn't carry over
    this.deps.onRecreated(receipt);
    await this.run();
  }

  private nextAttempt(reason: "server" | "network"): number {
    return this.retry.kind === "backoff" && this.retry.reason === reason
      ? this.retry.attempt + 1
      : 1;
  }
}
