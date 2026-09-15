/**
 * Base URL of the receipt-splitter API, without a trailing slash.
 *
 * NEXT_PUBLIC_* variables are inlined at build time, so changing the URL requires a rebuild.
 */
export function apiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!raw || raw.trim() === "") {
    throw new Error("NEXT_PUBLIC_API_BASE_URL is not set");
  }
  return raw.trim().replace(/\/+$/, "");
}
