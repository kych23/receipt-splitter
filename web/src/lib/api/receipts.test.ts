import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse } from "@/test/fixtures";
import {
  ApiError,
  createReceipt,
  deleteReceipt,
  getReceipt,
  SAVE_TIMEOUT_MS,
  saveReceipt,
  type SaveReceiptRequest,
} from "./receipts";

const BODY: SaveReceiptRequest = {
  content: { currency: "USD", lines: [], tax_lines: [] },
  participants: [],
  assignments: {},
};

describe("receipts API client", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test/");
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("createReceipt posts and returns the receipt", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ id: "r1" }, 201));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createReceipt(true)).resolves.toEqual({ id: "r1" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/v1/receipts");
    expect(init).toMatchObject({ method: "POST", body: '{"example":true}' });
  });

  it("createReceipt throws ApiError with Retry-After on 429", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ detail: "x" }, 429, { "Retry-After": "120" }),
        ),
    );
    await expect(createReceipt(false)).rejects.toMatchObject({
      status: 429,
      retryAfterS: 120,
    });
  });

  it("createReceipt throws a network ApiError when fetch rejects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    const error = await createReceipt(false).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBeNull();
  });

  it("getReceipt returns null for a malformed id (422)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: [] }, 422)),
    );
    await expect(getReceipt("not-a-uuid")).resolves.toBeNull();
  });

  it("getReceipt returns null on 404 and throws on 500", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "x" }, 404)),
    );
    await expect(getReceipt("r1")).resolves.toBeNull();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "x" }, 500)),
    );
    await expect(getReceipt("r1")).rejects.toMatchObject({ status: 500 });
  });

  it("deleteReceipt resolves on 204 and 404, throws otherwise", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(null, 204)));
    await expect(deleteReceipt("r1")).resolves.toBeUndefined();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "x" }, 404)),
    );
    await expect(deleteReceipt("r1")).resolves.toBeUndefined();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "x" }, 503)),
    );
    await expect(deleteReceipt("r1")).rejects.toMatchObject({ status: 503 });
  });

  it.each([
    [200, { id: "r1" }, {}, { kind: "saved", receipt: { id: "r1" } }],
    [404, { detail: "x" }, {}, { kind: "not_found" }],
    [
      429,
      { detail: "x" },
      { "Retry-After": "7" },
      { kind: "rate_limited", retryAfterS: 7 },
    ],
    [429, { detail: "x" }, {}, { kind: "rate_limited", retryAfterS: 60 }],
    [413, { detail: "x" }, {}, { kind: "rejected" }],
    [422, { detail: [] }, {}, { kind: "rejected" }],
    [500, { detail: "x" }, {}, { kind: "server_error" }],
    [502, { detail: "x" }, {}, { kind: "server_error" }],
  ])("saveReceipt maps HTTP %i", async (status, body, headers, expected) => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(body, status, headers));
    vi.stubGlobal("fetch", fetchMock);
    await expect(saveReceipt("r1", BODY)).resolves.toEqual(expected);
    expect(fetchMock.mock.calls[0][0]).toBe("http://api.test/v1/receipts/r1");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "PUT" });
  });

  it("saveReceipt maps a rejected fetch to network_error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(saveReceipt("r1", BODY)).resolves.toEqual({
      kind: "network_error",
    });
  });

  function hangingFetch() {
    return vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_, reject) => {
          init.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
  }

  it("saveReceipt times out after 15 s as network_error", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", hangingFetch());
    const result = saveReceipt("r1", BODY);
    await vi.advanceTimersByTimeAsync(SAVE_TIMEOUT_MS - 1);
    let settled = false;
    void result.then(() => (settled = true));
    await Promise.resolve();
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await expect(result).resolves.toEqual({ kind: "network_error" });
  });

  it("saveReceipt rejects when the caller aborts", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const controller = new AbortController();
    const result = saveReceipt("r1", BODY, controller.signal);
    controller.abort();
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
  });
});
