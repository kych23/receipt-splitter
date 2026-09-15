import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiStatus } from "./ApiStatus";

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ApiStatus", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
  });

  it("shows ok when the API and database are ready", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ status: "ok", database: "ok" }, 200));
    vi.stubGlobal("fetch", fetchMock);

    render(<ApiStatus />);

    expect(await screen.findByText("API: ok")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/readyz",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("shows database unavailable on 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ status: "unavailable", database: "error" }, 503),
        ),
    );
    render(<ApiStatus />);
    expect(
      await screen.findByText("API: unavailable (database)"),
    ).toBeInTheDocument();
  });

  it("shows the HTTP status for other errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "x" }, 500)),
    );
    render(<ApiStatus />);
    expect(await screen.findByText("API error (HTTP 500)")).toBeInTheDocument();
  });

  it("treats an unparseable body as an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("not json", { status: 200 })),
    );
    render(<ApiStatus />);
    expect(await screen.findByText("API error (HTTP 200)")).toBeInTheDocument();
  });

  it("shows unreachable on network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    render(<ApiStatus />);
    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
  });

  it("shows misconfigured without calling fetch when the URL is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<ApiStatus />);
    expect(
      await screen.findByText("API URL not configured"),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("aborts the request on unmount", async () => {
    let capturedSignal: AbortSignal | undefined;
    let capturedPromise: Promise<Response> | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => {
        capturedSignal = init.signal ?? undefined;
        capturedPromise = new Promise<Response>((_resolve, reject) => {
          capturedSignal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
        return capturedPromise;
      }),
    );

    const { unmount } = render(<ApiStatus />);
    expect(screen.getByText("Checking API…")).toBeInTheDocument();
    unmount();

    expect(capturedSignal?.aborted).toBe(true);
    // The promise rejects by design; wait for the component's rejection handler to run.
    await capturedPromise?.catch(() => undefined);
  });
});
