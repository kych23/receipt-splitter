import { apiBaseUrl } from "./config";
import type { components } from "./schema";

export type ReceiptResponse = components["schemas"]["ReceiptResponse"];
export type SaveReceiptRequest = components["schemas"]["SaveReceiptRequest"];
export type ReceiptLine = components["schemas"]["ReceiptLine"];
export type TaxLine = components["schemas"]["TaxLine"];
export type ParsedReceipt = components["schemas"]["ParsedReceipt"];
export type AllocationProblemCode =
  components["schemas"]["AllocationProblem"]["code"];
export type AllocationWarning = components["schemas"]["AllocationWarning"];

export const SAVE_TIMEOUT_MS = 15_000;
const DEFAULT_RETRY_AFTER_S = 60;

/** A failed API call. `status` is null when the request never got an HTTP response. */
export class ApiError extends Error {
  constructor(
    public readonly status: number | null,
    public readonly retryAfterS: number | null = null,
  ) {
    super(status === null ? "network error" : `HTTP ${status}`);
    this.name = "ApiError";
  }
}

export type SaveResult =
  | { kind: "saved"; receipt: ReceiptResponse }
  | { kind: "not_found" }
  | { kind: "rate_limited"; retryAfterS: number }
  | { kind: "rejected" }
  | { kind: "server_error" }
  | { kind: "network_error" };

function retryAfterSeconds(response: Response): number {
  const value = Number(response.headers.get("Retry-After"));
  return Number.isFinite(value) && value > 0
    ? Math.ceil(value)
    : DEFAULT_RETRY_AFTER_S;
}

function receiptsUrl(id?: string): string {
  let base: string;
  try {
    base = apiBaseUrl();
  } catch {
    throw new ApiError(null);
  }
  return id === undefined
    ? `${base}/v1/receipts`
    : `${base}/v1/receipts/${encodeURIComponent(id)}`;
}

async function send(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, { cache: "no-store", ...init });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new ApiError(null);
  }
}

function failure(response: Response): ApiError {
  return new ApiError(
    response.status,
    response.status === 429 ? retryAfterSeconds(response) : null,
  );
}

export async function createReceipt(
  example: boolean,
): Promise<ReceiptResponse> {
  const response = await send(receiptsUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ example }),
  });
  if (response.status !== 201) throw failure(response);
  return (await response.json()) as ReceiptResponse;
}

/**
 * The receipt, or null if it doesn't exist, has expired, or the id is malformed (422) — none of
 * which a retry can fix.
 */
export async function getReceipt(id: string): Promise<ReceiptResponse | null> {
  const response = await send(receiptsUrl(id), { method: "GET" });
  if (response.status === 404 || response.status === 422) return null;
  if (response.status !== 200) throw failure(response);
  return (await response.json()) as ReceiptResponse;
}

/**
 * Replace the receipt's state. Never throws for HTTP or network failures (they come back as a
 * SaveResult); rejects only when the caller's `signal` aborts. A request that takes longer than
 * SAVE_TIMEOUT_MS counts as a network error.
 *
 * The timeout and the caller's signal are combined by hand rather than with AbortSignal.any, which
 * iOS Safari only has from 17.4.
 */
export async function saveReceipt(
  id: string,
  body: SaveReceiptRequest,
  signal?: AbortSignal,
): Promise<SaveResult> {
  signal?.throwIfAborted();
  let url: string;
  try {
    url = receiptsUrl(id);
  } catch {
    return { kind: "network_error" };
  }

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, SAVE_TIMEOUT_MS);
  const forwardAbort = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", forwardAbort);

  try {
    const response = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: controller.signal,
    });
    const { status } = response;
    if (status === 200) {
      return {
        kind: "saved",
        receipt: (await response.json()) as ReceiptResponse,
      };
    }
    if (status === 404) return { kind: "not_found" };
    if (status === 429)
      return { kind: "rate_limited", retryAfterS: retryAfterSeconds(response) };
    if (status >= 500) return { kind: "server_error" };
    return { kind: "rejected" }; // 413, 422 or another 4xx: retrying the same body can't help
  } catch (error) {
    if (signal?.aborted && !timedOut) throw error;
    return { kind: "network_error" };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forwardAbort);
  }
}

/** Delete the receipt. Already-gone (404) counts as success. */
export async function deleteReceipt(id: string): Promise<void> {
  const response = await send(receiptsUrl(id), { method: "DELETE" });
  if (response.status !== 204 && response.status !== 404)
    throw failure(response);
}
