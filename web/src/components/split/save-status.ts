import type { SaveStatus } from "@/lib/autosave";

/** What to tell the user about saving; null when nothing needs saying. Shared by bar and sheet. */
export function statusMessage(status: SaveStatus): string | null {
  switch (status.kind) {
    case "idle":
      return null;
    case "invalid":
      return "Fix highlighted rows to update totals";
    case "offline":
      return "Offline — will retry";
    case "paused":
      return "Saving paused — too many changes";
    case "rejected":
      return "Couldn't save — something doesn't look right. Your edits are still here.";
    case "gave_up":
      return "Couldn't save — try again";
  }
}

/** A save is queued or in flight (as opposed to blocked on the user or the network). */
export function savePending(dirty: boolean, status: SaveStatus): boolean {
  return dirty && status.kind === "idle";
}
