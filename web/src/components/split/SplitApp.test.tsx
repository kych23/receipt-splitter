import { act, fireEvent, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReceiptResponse } from "@/lib/api/receipts";
import {
  resetStoredReceiptIdForTests,
  setStoredReceiptId,
} from "@/lib/stored-receipt-id";
import { exampleReceipt, jsonResponse } from "@/test/fixtures";
import { SplitApp } from "./SplitApp";

const EXAMPLE = exampleReceipt();
const RECEIPT_URL = `http://api.test/v1/receipts/${EXAMPLE.id}`;

type Call = {
  method: string;
  url: string;
  body: unknown;
  signal?: AbortSignal | null;
};
type Reply = Response | "network" | "hang";

/** fetch mock: replies are taken per method from queues; the last reply for a method repeats. */
function mockApi(replies: Partial<Record<string, Reply[]>>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn((url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    calls.push({
      method,
      url,
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
      signal: init.signal,
    });
    const queue = replies[method] ?? [];
    const reply = queue.length > 1 ? queue.shift()! : queue[0];
    if (reply === undefined) throw new Error(`unexpected ${method} ${url}`);
    if (reply === "network")
      return Promise.reject(new TypeError("Failed to fetch"));
    if (reply === "hang") {
      return new Promise<Response>((_, reject) =>
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        ),
      );
    }
    return Promise.resolve(reply.clone());
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, puts: () => calls.filter((c) => c.method === "PUT") };
}

/** A PUT reply echoing the example receipt (its allocation is what the bar shows). */
const saved = (receipt: ReceiptResponse = EXAMPLE) => jsonResponse(receipt);

async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function openExample(): Promise<void> {
  render(<SplitApp />);
  fireEvent.click(screen.getByRole("button", { name: "Try an example" }));
  await flush();
}

const bar = () => screen.getByRole("contentinfo", { name: "Totals" });
const taxInput = () => screen.getByLabelText("Tax on receipt");

describe("SplitApp", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
    window.localStorage.clear();
    resetStoredReceiptIdForTests();
  });
  afterEach(() => {
    vi.useRealTimers();
    resetStoredReceiptIdForTests();
  });

  it("renders a neutral Loading… on the server, with no start buttons", () => {
    const html = renderToString(<SplitApp />);
    expect(html).toContain("Loading…");
    expect(html).not.toContain("Start a new receipt");
  });

  it("loads the example with three totals", async () => {
    const api = mockApi({ POST: [jsonResponse(EXAMPLE, 201)] });
    await openExample();
    expect(api.calls[0]).toMatchObject({
      method: "POST",
      body: { example: true },
    });
    expect(bar()).toHaveTextContent("Alex $4.26 · Sam $15.03 · Jordan $18.80");
    expect(screen.getByText("Example receipt")).toBeInTheDocument();
    expect(window.localStorage.getItem("receiptsplit.receiptId")).toBe(
      EXAMPLE.id,
    );
  });

  it("debounces edits into one PUT with the latest state", async () => {
    const api = mockApi({ POST: [jsonResponse(EXAMPLE, 201)], PUT: [saved()] });
    await openExample();
    fireEvent.change(taxInput(), { target: { value: "1" } });
    await flush(300);
    fireEvent.change(taxInput(), { target: { value: "2.50" } });
    await flush(599);
    expect(api.puts()).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Copy summary" })).toBeDisabled();
    await flush(1);
    expect(api.puts()).toHaveLength(1);
    const body = api.puts()[0].body as ReceiptResponse;
    expect(body.content.tax_lines).toEqual([
      { label: "NY TAX 8%", amount_cents: 250 },
    ]);
    expect(api.puts()[0].url).toBe(RECEIPT_URL);
    await flush();
    expect(screen.getByRole("button", { name: "Copy summary" })).toBeEnabled();
  });

  it("does not send an invalid row and highlights it", async () => {
    const api = mockApi({ POST: [jsonResponse(EXAMPLE, 201)], PUT: [saved()] });
    await openExample();
    fireEvent.change(screen.getByLabelText("Item 1 price"), {
      target: { value: "abc" },
    });
    await flush(600);
    expect(api.puts()).toHaveLength(0);
    expect(bar()).toHaveTextContent("Fix highlighted rows to update totals");
    expect(screen.getByLabelText("Item 1 price").closest("li")).toHaveAttribute(
      "data-invalid",
    );
  });

  it("server errors retry, then offer Retry after the 6th failed request", async () => {
    const api = mockApi({
      POST: [jsonResponse(EXAMPLE, 201)],
      PUT: [jsonResponse({ detail: "x" }, 500)],
    });
    await openExample();
    fireEvent.change(taxInput(), { target: { value: "1" } });
    await flush(600);
    for (const delay of [2000, 4000, 8000, 16000, 32000]) await flush(delay);
    expect(api.puts()).toHaveLength(6);
    expect(bar()).toHaveTextContent("Couldn't save — try again");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await flush(600);
    expect(api.puts()).toHaveLength(7);
  });

  it("moves edits to a new receipt when a save returns 404, without losing them", async () => {
    const replacement = {
      ...exampleReceipt(),
      id: "33333333-3333-4333-8333-333333333333",
    };
    const api = mockApi({
      POST: [
        jsonResponse(EXAMPLE, 201),
        jsonResponse({ ...replacement, is_example: false }, 201),
      ],
      PUT: [
        jsonResponse({ detail: "receipt not found" }, 404),
        jsonResponse(replacement),
      ],
    });
    await openExample();
    fireEvent.change(taxInput(), { target: { value: "1" } });
    await flush(600);
    await flush();
    const [first, second] = api.puts();
    expect(first.url).toBe(RECEIPT_URL);
    expect(second.url).toBe(`http://api.test/v1/receipts/${replacement.id}`);
    expect(
      (second.body as ReceiptResponse).content.tax_lines[0].amount_cents,
    ).toBe(100);
    expect(api.calls.filter((c) => c.method === "POST")[1].body).toEqual({
      example: false,
    });
    expect(window.localStorage.getItem("receiptsplit.receiptId")).toBe(
      replacement.id,
    );
    expect(taxInput()).toHaveValue("1"); // still the same editor, edits intact
  });

  it("shows 'This receipt expired' when a stored receipt is gone on reopen", async () => {
    setStoredReceiptId(EXAMPLE.id);
    mockApi({ GET: [jsonResponse({ detail: "receipt not found" }, 404)] });
    render(<SplitApp />);
    await flush();
    expect(screen.getByText("This receipt expired")).toBeInTheDocument();
    expect(window.localStorage.getItem("receiptsplit.receiptId")).toBeNull();
  });

  it("delete during an in-flight save aborts it and returns to the start screen", async () => {
    const api = mockApi({
      POST: [jsonResponse(EXAMPLE, 201)],
      PUT: ["hang"],
      DELETE: [jsonResponse(null, 204)],
    });
    await openExample();
    fireEvent.change(taxInput(), { target: { value: "1" } });
    await flush(600);
    const put = api.puts()[0];
    fireEvent.click(screen.getByRole("button", { name: "Delete receipt" }));
    await flush();
    expect(put.signal?.aborted).toBe(true);
    expect(api.calls.at(-1)).toMatchObject({
      method: "DELETE",
      url: RECEIPT_URL,
    });
    expect(
      screen.getByRole("button", { name: "Try an example" }),
    ).toBeInTheDocument();
  });

  it("stays on the receipt when delete fails", async () => {
    mockApi({
      POST: [jsonResponse(EXAMPLE, 201)],
      DELETE: [jsonResponse({ detail: "x" }, 500)],
    });
    await openExample();
    fireEvent.click(screen.getByRole("button", { name: "Delete receipt" }));
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn't delete — try again",
    );
    expect(bar()).toBeInTheDocument();
  });

  it("unmount aborts the in-flight save", async () => {
    const api = mockApi({ POST: [jsonResponse(EXAMPLE, 201)], PUT: ["hang"] });
    const { unmount } = render(<SplitApp />);
    fireEvent.click(screen.getByRole("button", { name: "Try an example" }));
    await flush();
    fireEvent.change(taxInput(), { target: { value: "1" } });
    await flush(600);
    const put = api.puts()[0];
    expect(put.signal?.aborted).toBe(false);
    unmount();
    expect(put.signal?.aborted).toBe(true);
  });

  it("reopens a stored receipt; 404 goes to the start screen", async () => {
    setStoredReceiptId(EXAMPLE.id);
    mockApi({ GET: [jsonResponse({ detail: "receipt not found" }, 404)] });
    render(<SplitApp />);
    await flush();
    expect(
      screen.getByRole("button", { name: "Try an example" }),
    ).toBeInTheDocument();
  });

  it("shows Can't reach ReceiptSplit on a failed load, and Retry loads it", async () => {
    setStoredReceiptId(EXAMPLE.id);
    const api = mockApi({ GET: ["network", jsonResponse(EXAMPLE)] });
    render(<SplitApp />);
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Can't reach ReceiptSplit",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await flush();
    expect(api.calls.filter((c) => c.method === "GET")).toHaveLength(2);
    expect(bar()).toHaveTextContent("Alex $4.26");
  });

  it("can leave a receipt that keeps failing to load", async () => {
    setStoredReceiptId(EXAMPLE.id);
    mockApi({ GET: [jsonResponse({ detail: "internal error" }, 500)] });
    render(<SplitApp />);
    await flush();
    fireEvent.click(
      screen.getByRole("button", { name: "Start a new receipt" }),
    );
    await flush();
    expect(
      screen.getByRole("button", { name: "Try an example" }),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem("receiptsplit.receiptId")).toBeNull();
  });

  it.each([
    [
      jsonResponse({ detail: "x" }, 429, { "Retry-After": "90" }),
      "Too many new receipts from this network — try again in 2 min",
    ],
    [
      jsonResponse({ detail: "x" }, 503),
      "ReceiptSplit is busy — try again in a few minutes",
    ],
    ["network" as const, "Can't reach ReceiptSplit — try again"],
  ])("start errors show a message (%#)", async (reply, message) => {
    mockApi({ POST: [reply] });
    render(<SplitApp />);
    fireEvent.click(
      screen.getByRole("button", { name: "Start a new receipt" }),
    );
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent(message);
  });
});
