import type { ReceiptResponse } from "@/lib/api/receipts";
import example from "./example-receipt.json";

/**
 * The server's example receipt (generated from api/app/receipts/example.py; an API test keeps the
 * two in sync). Alex 426, Sam 1503, Jordan 1880; total 3809.
 */
export function exampleReceipt(): ReceiptResponse {
  return structuredClone(example) as ReceiptResponse;
}

export const ALEX = "00000000-0000-4000-8000-000000000001";
export const SAM = "00000000-0000-4000-8000-000000000002";
export const JORDAN = "00000000-0000-4000-8000-000000000003";

export function emptyReceipt(
  overrides: Partial<ReceiptResponse> = {},
): ReceiptResponse {
  return {
    id: "22222222-2222-4222-8222-222222222222",
    is_example: false,
    updated_at: "2026-09-24T12:00:00Z",
    expires_at: "2026-09-25T12:00:00Z",
    content: { currency: "USD", lines: [], tax_lines: [] },
    participants: [],
    assignments: {},
    allocation: null,
    allocation_problem: { code: "no_participants", detail: "no participants" },
    ...overrides,
  };
}

/** A fetch Response with a JSON body (no body for 204). */
export function jsonResponse(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}
