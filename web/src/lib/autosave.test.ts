import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { emptyReceipt, exampleReceipt } from "@/test/fixtures";
import {
  ApiError,
  type SaveReceiptRequest,
  type SaveResult,
} from "./api/receipts";
import { Autosaver, DEBOUNCE_MS, type SaveStatus } from "./autosave";
import { type EditorState, initialState, reducer } from "./receipt-state";

type Deferred = {
  resolve: (r: SaveResult) => void;
  reject: (e: unknown) => void;
};

function harness() {
  let state: EditorState = reducer(initialState(), {
    type: "loadFromServer",
    receipt: exampleReceipt(),
  });
  const statuses: SaveStatus[] = [];
  const sent: SaveReceiptRequest[] = [];
  const sentTo: string[] = [];
  const pending: Deferred[] = [];
  const onSaved = vi.fn((_: unknown, revision: number) => {
    state = reducer(state, { type: "markSaved", revision });
  });
  const onRecreated = vi.fn();
  const create = vi.fn(() =>
    Promise.resolve(emptyReceipt({ id: `new-${create.mock.calls.length}` })),
  );
  const saver = new Autosaver({
    receiptId: "orig",
    save: (id, body, signal) =>
      new Promise<SaveResult>((resolve, reject) => {
        sentTo.push(id);
        sent.push(body);
        signal.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
        pending.push({ resolve, reject });
      }),
    create,
    getState: () => state,
    onSaved,
    onRecreated,
    onStatus: (s) => statuses.push(s),
  });
  return {
    saver,
    sent,
    pending,
    statuses,
    sentTo,
    create,
    onSaved,
    onRecreated,
    get state() {
      return state;
    },
    setTax(input: string) {
      state = reducer(state, { type: "setTax", input });
      saver.edited();
    },
    respond(result: SaveResult, index = pending.length - 1) {
      pending[index].resolve(result);
    },
    lastStatus: () => statuses[statuses.length - 1],
  };
}

const saved = (): SaveResult => ({ kind: "saved", receipt: emptyReceipt() });

describe("Autosaver", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("debounces edits into one save of the latest state", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS - 1);
    h.setTax("2");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS - 1);
    h.setTax("3");
    expect(h.sent).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(h.sent).toHaveLength(1);
    expect(h.sent[0].content.tax_lines).toEqual([
      { label: "NY TAX 8%", amount_cents: 300 },
    ]);
    h.respond(saved());
    await vi.advanceTimersByTimeAsync(0);
    expect(h.state.dirty).toBe(false);
  });

  it("an edit during an in-flight save triggers a second save", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.setTax("2");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(h.sent).toHaveLength(1); // still one in flight
    h.respond(saved());
    await vi.advanceTimersByTimeAsync(0);
    expect(h.state.dirty).toBe(true); // the response was for an older revision
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(h.sent).toHaveLength(2);
    expect(h.sent[1].content.tax_lines[0].amount_cents).toBe(200);
    h.respond(saved());
    await vi.advanceTimersByTimeAsync(0);
    expect(h.state.dirty).toBe(false);
  });

  it("does not send invalid state and reports the rows", async () => {
    const h = harness();
    h.setTax("abc");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(h.sent).toHaveLength(0);
    expect(h.lastStatus()).toEqual({ kind: "invalid", lineIds: ["tax"] });
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(h.sent).toHaveLength(1);
    expect(h.lastStatus()).toEqual({ kind: "idle" });
  });

  it("server errors retry 5 times with backoff, then give up; Retry restarts", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    for (const delay of [2000, 4000, 8000, 16000, 32000]) {
      h.respond({ kind: "server_error" });
      await vi.advanceTimersByTimeAsync(delay - 1);
      const before = h.sent.length;
      await vi.advanceTimersByTimeAsync(1);
      expect(h.sent.length).toBe(before + 1);
    }
    expect(h.sent).toHaveLength(6);
    h.respond({ kind: "server_error" });
    await vi.advanceTimersByTimeAsync(120_000);
    expect(h.sent).toHaveLength(6);
    expect(h.lastStatus()).toEqual({ kind: "gave_up" });
    h.saver.retryNow();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(h.sent).toHaveLength(7);
  });

  it("an edit during server backoff resets the retry counter", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.respond({ kind: "server_error" }); // attempt 1, retry in 2 s
    await vi.advanceTimersByTimeAsync(2000);
    h.respond({ kind: "server_error" }); // attempt 2, retry in 4 s
    await vi.advanceTimersByTimeAsync(0);
    h.setTax("2"); // resets: normal debounce
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(h.sent).toHaveLength(3);
    h.respond({ kind: "server_error" }); // attempt 1 again: 2 s, not 8 s
    await vi.advanceTimersByTimeAsync(2000);
    expect(h.sent).toHaveLength(4);
  });

  it("network errors show offline and retry 2, 4, 8 s then every 30 s", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    for (const delay of [2000, 4000, 8000, 30_000, 30_000]) {
      h.respond({ kind: "network_error" });
      await vi.advanceTimersByTimeAsync(0);
      expect(h.lastStatus()).toEqual({ kind: "offline" });
      const before = h.sent.length;
      await vi.advanceTimersByTimeAsync(delay);
      expect(h.sent.length).toBe(before + 1);
    }
    h.respond(saved());
    await vi.advanceTimersByTimeAsync(0);
    expect(h.lastStatus()).toEqual({ kind: "idle" });
  });

  it("lost response: the retry after a network error sends the newest state", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.respond({ kind: "network_error" });
    await vi.advanceTimersByTimeAsync(0);
    h.setTax("7");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(h.sent.at(-1)?.content.tax_lines[0].amount_cents).toBe(700);
  });

  it("rate limiting pauses; edits during the pause produce one save when it ends", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.respond({ kind: "rate_limited", retryAfterS: 10 });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.lastStatus()).toEqual({ kind: "paused" });
    h.setTax("2");
    h.setTax("3");
    await vi.advanceTimersByTimeAsync(9_999);
    expect(h.sent).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.sent).toHaveLength(2);
    expect(h.sent[1].content.tax_lines[0].amount_cents).toBe(300);
  });

  it("rejected shows a message and does not retry until the next edit", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.respond({ kind: "rejected" });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.sent).toHaveLength(1);
    expect(h.lastStatus()).toEqual({ kind: "rejected" });
    h.setTax("2");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(h.sent).toHaveLength(2);
  });

  it("not_found moves the latest edits to a new receipt instead of dropping them", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.setTax("2"); // edit while the doomed save is in flight
    h.respond({ kind: "not_found" });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.create).toHaveBeenCalledOnce();
    expect(h.onRecreated).toHaveBeenCalledWith(
      expect.objectContaining({ id: "new-1" }),
    );
    expect(h.saver.receiptId).toBe("new-1");
    expect(h.sentTo).toEqual(["orig", "new-1"]);
    expect(h.sent[1].content.tax_lines[0].amount_cents).toBe(200);
    h.respond(saved());
    await vi.advanceTimersByTimeAsync(0);
    expect(h.state.dirty).toBe(false);
  });

  it("an offline create shows Offline and retries on its own", async () => {
    const h = harness();
    h.create.mockRejectedValueOnce(new ApiError(null));
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.respond({ kind: "not_found" });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.lastStatus()).toEqual({ kind: "offline" });
    await vi.advanceTimersByTimeAsync(2000); // network backoff: re-send, 404, recreate
    h.respond({ kind: "not_found" });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.create).toHaveBeenCalledTimes(2);
    expect(h.sentTo.at(-1)).toBe("new-2");
  });

  it("a rate-limited create pauses for Retry-After, then recreates", async () => {
    const h = harness();
    h.create.mockRejectedValueOnce(new ApiError(429, 30));
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.respond({ kind: "not_found" });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.lastStatus()).toEqual({ kind: "paused" });
    await vi.advanceTimersByTimeAsync(29_999);
    expect(h.sent).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    h.respond({ kind: "not_found" });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.create).toHaveBeenCalledTimes(2);
  });

  it("server-error backoff doesn't carry over to the replacement", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    for (const delay of [2000, 4000, 8000]) {
      h.respond({ kind: "server_error" });
      await vi.advanceTimersByTimeAsync(delay); // attempts 1-3
    }
    h.respond({ kind: "not_found" }); // recreate, save to new-1
    await vi.advanceTimersByTimeAsync(0);
    h.respond({ kind: "server_error" }); // attempt 1 again: retry in 2 s
    await vi.advanceTimersByTimeAsync(2000);
    expect(h.sentTo.filter((id) => id === "new-1")).toHaveLength(2);
  });

  it("keeps the edits and offers Retry when the replacement can't be created", async () => {
    const h = harness();
    h.create.mockRejectedValueOnce(new Error("offline"));
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.respond({ kind: "not_found" });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.lastStatus()).toEqual({ kind: "gave_up" });
    expect(h.state.dirty).toBe(true);
    h.saver.retryNow();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.respond({ kind: "not_found" });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.sentTo.at(-1)).toBe("new-2");
  });

  it("stops instead of looping when the replacement also 404s", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.respond({ kind: "not_found" });
    await vi.advanceTimersByTimeAsync(0);
    h.respond({ kind: "not_found" }); // the replacement 404s too
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.create).toHaveBeenCalledOnce();
    expect(h.lastStatus()).toEqual({ kind: "gave_up" });
    h.saver.retryNow(); // the user can try once more
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.respond({ kind: "not_found" });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.create).toHaveBeenCalledTimes(2);
  });

  it("a replacement that finishes after cancel is ignored", async () => {
    const h = harness();
    let finish: (r: ReturnType<typeof emptyReceipt>) => void = () => {};
    h.create.mockImplementationOnce(
      () => new Promise((resolve) => (finish = resolve)),
    );
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.respond({ kind: "not_found" });
    await vi.advanceTimersByTimeAsync(0);
    h.saver.cancel();
    finish(emptyReceipt({ id: "late" }));
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(h.onRecreated).not.toHaveBeenCalled();
    expect(h.sent).toHaveLength(1);
  });

  it("cancel aborts the in-flight save and pending timers", async () => {
    const h = harness();
    h.setTax("1");
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    h.setTax("2");
    h.saver.cancel();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.sent).toHaveLength(1);
    expect(h.onSaved).not.toHaveBeenCalled();
  });

  it("does nothing when the state is not dirty", async () => {
    const h = harness();
    h.saver.edited();
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    expect(h.sent).toHaveLength(0);
  });
});
