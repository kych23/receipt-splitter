"use client";

import type {
  AllocationProblemCode,
  AllocationWarning,
  ReceiptResponse,
} from "@/lib/api/receipts";
import type { SaveStatus } from "@/lib/autosave";
import { formatCents } from "@/lib/money";
import type { Person } from "@/lib/receipt-state";
import { PersonBadge } from "./PersonBadge";
import { statusMessage } from "./save-status";

/**
 * The bar stays one row at 375px. Two "$xxx.xx" totals plus "+K more" and the Details button fit
 * (about 324px of 343px); three do not, so from three people on it shows two plus "+K more".
 */
const MAX_INLINE_PEOPLE = 2;

type Props = {
  receipt: ReceiptResponse;
  dirty: boolean;
  status: SaveStatus;
  /** Items and deposits without a tag, from the local state. */
  untagged: number;
  onRetry: () => void;
  /** Open the per-person breakdown sheet. */
  onOpen: () => void;
  /** Local people list, for badge colours. */
  people: Person[];
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

export function TotalsBar({
  receipt,
  people,
  dirty,
  status,
  untagged,
  onRetry,
  onOpen,
}: Props): React.JSX.Element {
  const { allocation, allocation_problem: problem } = receipt;
  const names = new Map(
    receipt.participants.map((p) => [p.key, p.display_name]),
  );
  const colorIndex = new Map(people.map((p, index) => [p.key, index]));
  const saveMessage = statusMessage(status) ?? (dirty ? "Saving…" : null);
  const warning = allocation ? warningMessage(allocation.warnings) : null;
  const everyone = allocation?.participants ?? [];
  const shown = everyone.slice(0, MAX_INLINE_PEOPLE);
  const hidden = everyone.length - shown.length;

  return (
    <section
      aria-label="Totals"
      className="totals-bar sticky bottom-0 z-10 -mx-4 mt-6 rounded-t-2xl bg-ink px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] text-paper"
    >
      {allocation ? (
        <button
          type="button"
          aria-haspopup="dialog"
          onClick={onOpen}
          className="flex min-h-11 w-full items-center justify-between gap-3 text-left"
        >
          {/* Spans, not a list: a <button> may only hold phrasing content. */}
          <span className="flex min-w-0 flex-nowrap items-center gap-x-3">
            {/* Only the people clip if totals get huge; "+K more" must always stay visible. */}
            <span
              data-testid="totals-people"
              className="flex min-w-0 flex-nowrap items-center gap-x-3 overflow-hidden"
            >
              {shown.map((p) => {
                const name = names.get(p.participant_id) ?? "?";
                return (
                  <span
                    key={p.participant_id}
                    className="flex items-center gap-1.5"
                  >
                    <PersonBadge
                      name={name}
                      index={colorIndex.get(p.participant_id) ?? null}
                    />
                    {/* Name stays visible: initials collide (Sam / Sara) and colours repeat. */}
                    <span className="flex flex-col leading-tight">
                      <span className="max-w-[8ch] truncate text-xs">
                        {name}
                      </span>
                      <span className="font-mono font-semibold">
                        {formatCents(p.total_cents)}
                      </span>
                    </span>
                  </span>
                );
              })}
            </span>
            {hidden > 0 && (
              <span className="shrink-0 text-sm font-semibold whitespace-nowrap">
                +{hidden} more
              </span>
            )}
          </span>
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full border-2 border-paper">
            <span aria-hidden>⌃</span>
            <span className="sr-only">Details</span>
          </span>
        </button>
      ) : (
        <p className="flex min-h-11 items-center font-semibold">
          {problem && problemMessage(problem.code, untagged)}
        </p>
      )}
      {warning && <p className="text-sm">{warning}</p>}
      {saveMessage && (
        <div role="status" className="flex items-center gap-3 pt-1 text-sm">
          <span>{saveMessage}</span>
          {status.kind === "gave_up" && (
            <button
              type="button"
              className="min-h-11 rounded-full border-2 border-paper px-4 font-semibold"
              onClick={onRetry}
            >
              Retry
            </button>
          )}
        </div>
      )}
    </section>
  );
}
