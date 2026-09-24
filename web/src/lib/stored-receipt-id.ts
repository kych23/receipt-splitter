import { useSyncExternalStore } from "react";

/**
 * The id of the receipt this browser is working on, remembered across refreshes.
 *
 * An in-memory variable is the source of truth for this tab; localStorage is a best-effort copy, so
 * the app still works when storage is blocked (private mode, disabled site data). The server
 * snapshot is `undefined` ("not known yet") so server and first client render agree.
 */

const STORAGE_KEY = "receiptsplit.receiptId";

let current: string | null | undefined; // undefined = not read from storage yet
const listeners = new Set<() => void>();

function readStorage(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function getSnapshot(): string | null {
  if (current === undefined) current = readStorage();
  return current;
}

function getServerSnapshot(): undefined {
  return undefined;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useStoredReceiptId(): string | null | undefined {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export function setStoredReceiptId(id: string | null): void {
  current = id;
  for (const listener of listeners) listener();
  try {
    if (id === null) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Storage unavailable: the in-memory value still works until the tab is closed.
  }
}

/** Test hook: forget the in-memory value so the next read goes back to storage. */
export function resetStoredReceiptIdForTests(): void {
  current = undefined;
}
