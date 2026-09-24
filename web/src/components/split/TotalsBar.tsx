"use client";

import type {
  AllocationProblemCode,
  AllocationWarning,
  ReceiptResponse,
} from "@/lib/api/receipts";
import type { SaveStatus } from "@/lib/autosave";
import { formatCents } from "@/lib/money";
import { button } from "./styles";

type Props = {
  receipt: ReceiptResponse;
  dirty: boolean;
  status: SaveStatus;
  /** Items and deposits without a tag, from the local state. */
  untagged: number;
  onRetry: () => void;
};

function problemMessage(code: AllocationProblemCode, untagged: number): string {
  switch (code) {
    case "no_participants":
      return "Add the people splitting this receipt";
    case "unassigned_line":
      return `Tag every item — ${untagged} left`;
    case "no_assignable_lines":
      return "Add an item";
    default:
      return "Can't split yet — check the items";
  }
}

function warningMessage(warnings: AllocationWarning[]): string | null {
  if (
    warnings.includes("unknown_taxability") ||
    warnings.includes("tax_fallback_proportional")
  ) {
    return "Mark every item taxed or not — tax may be off";
  }
  if (warnings.includes("tax_without_taxable_lines")) {
    return "Tax entered but no item is marked taxed";
  }
  return null;
}

function statusMessage(status: SaveStatus): string | null {
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

export function TotalsBar({
  receipt,
  dirty,
  status,
  untagged,
  onRetry,
}: Props): React.JSX.Element {
  const { allocation, allocation_problem: problem } = receipt;
  const names = new Map(
    receipt.participants.map((p) => [p.key, p.display_name]),
  );
  const saveMessage = statusMessage(status) ?? (dirty ? "Saving…" : null);
  const warning = allocation ? warningMessage(allocation.warnings) : null;

  return (
    <footer
      aria-label="Totals"
      className="sticky bottom-0 border-t border-neutral-200 bg-background px-4 py-3 dark:border-neutral-800"
    >
      <p className={`font-semibold ${dirty ? "opacity-50" : ""}`}>
        {allocation
          ? allocation.participants
              .map(
                (p) =>
                  `${names.get(p.participant_id) ?? "?"} ${formatCents(p.total_cents)}`,
              )
              .join(" · ")
          : problem && problemMessage(problem.code, untagged)}
      </p>
      {warning && (
        <p className="text-sm text-amber-700 dark:text-amber-400">{warning}</p>
      )}
      {saveMessage && (
        <div role="status" className="flex items-center gap-2 text-sm">
          <span>{saveMessage}</span>
          {status.kind === "gave_up" && (
            <button type="button" className={button} onClick={onRetry}>
              Retry
            </button>
          )}
        </div>
      )}
    </footer>
  );
}
