"use client";

import { useState } from "react";
import type { ReceiptResponse } from "@/lib/api/receipts";
import { formatCents } from "@/lib/money";
import type { SaveStatus } from "@/lib/autosave";
import type { EditorState } from "@/lib/receipt-state";
import { summaryText } from "@/lib/summary-text";
import { PersonBadge } from "./PersonBadge";
import { savePending, statusMessage } from "./save-status";
import { button, primaryButton } from "./styles";

function copyHint(noAllocation: boolean, pending: boolean): string {
  if (noAllocation) return "Finish tagging to copy";
  if (pending) return "Saving… copy when done";
  return "Copy works once your changes are saved";
}

type Props = {
  receipt: ReceiptResponse;
  state: EditorState;
  /** Local edits aren't reflected in `receipt` yet (unsaved or invalid). */
  stale: boolean;
  dirty: boolean;
  status: SaveStatus;
  onRetry: () => void;
};

function lineNames(state: EditorState): Map<string, string> {
  const names = new Map<string, string>();
  for (const item of state.items)
    names.set(item.lineId, item.name.trim() || "(unnamed item)");
  for (const line of state.readOnlyLines) names.set(line.line_id, line.name);
  return names;
}

function AmountRow({
  label,
  cents,
}: {
  label: string;
  cents: number;
}): React.JSX.Element {
  return (
    <li className="flex justify-between gap-3">
      <span>{label}</span>
      <span className="font-mono">{formatCents(cents)}</span>
    </li>
  );
}

/** Each person's lines, tax and total, plus Copy summary. Shown inside the totals sheet. */
export function Summary({
  receipt,
  state,
  stale,
  dirty,
  status,
  onRetry,
}: Props): React.JSX.Element {
  const [fallbackText, setFallbackText] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const { allocation } = receipt;
  const names = lineNames(state);
  const people = new Map(
    receipt.participants.map((p) => [p.key, p.display_name]),
  );
  const colorIndex = new Map(state.people.map((p, index) => [p.key, index]));
  const canCopy = allocation !== null && !stale;
  const pending = savePending(dirty, status);
  // The sheet is modal, so the bar's status and Retry are behind the backdrop: repeat them here.
  const blocked = statusMessage(status);

  async function copy(): Promise<void> {
    const text = summaryText(receipt);
    if (text === null) return;
    const clipboard =
      typeof navigator === "undefined" ? undefined : navigator.clipboard;
    if (typeof clipboard?.writeText === "function") {
      try {
        await clipboard.writeText(text);
        setFallbackText(null);
        setCopied(true);
        return;
      } catch {
        // Fall through to the manual-copy textarea.
      }
    }
    setCopied(false);
    setFallbackText(text);
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Stale state is said in text, not by fading: opacity would drop contrast below AA. */}
      {(pending || blocked) && (
        <div role="status" className="flex items-center gap-3 text-sm">
          <span className={pending ? "text-ink-muted" : "text-danger"}>
            {pending ? "Updating after your last edit…" : blocked}
          </span>
          {status.kind === "gave_up" && (
            <button type="button" className={button} onClick={onRetry}>
              Retry
            </button>
          )}
        </div>
      )}
      {allocation && (
        <ul className="flex flex-col" aria-busy={pending}>
          {allocation.participants.map((person) => {
            const name =
              people.get(person.participant_id) ?? "(removed person)";
            return (
              <li
                key={person.participant_id}
                className="rule-dashed py-3 first:border-t-0"
              >
                <p className="flex items-center justify-between gap-3 font-bold">
                  <span className="flex items-center gap-2">
                    <PersonBadge
                      name={name}
                      index={colorIndex.get(person.participant_id) ?? null}
                    />
                    {name}
                  </span>
                  <span className="font-mono">
                    {formatCents(person.total_cents)}
                  </span>
                </p>
                <ul className="mt-2 flex flex-col gap-0.5 pl-9 text-sm">
                  {person.line_shares.map((share) => (
                    <li
                      key={share.line_id}
                      className="flex justify-between gap-3"
                    >
                      <span>
                        {names.get(share.line_id) ?? "(edited item)"}
                        {share.split_count > 1 && (
                          <span className="text-ink-muted">
                            {" "}
                            (split {share.split_count})
                          </span>
                        )}
                      </span>
                      <span className="font-mono">
                        {formatCents(share.share_cents)}
                      </span>
                    </li>
                  ))}
                  {person.receipt_discounts_cents !== 0 && (
                    <AmountRow
                      label="Discounts"
                      cents={person.receipt_discounts_cents}
                    />
                  )}
                  {person.fees_cents !== 0 && (
                    <AmountRow label="Fees" cents={person.fees_cents} />
                  )}
                  <AmountRow label="Tax" cents={person.tax_cents} />
                </ul>
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex flex-col gap-2">
        <button
          type="button"
          className={primaryButton}
          disabled={!canCopy}
          onClick={() => void copy()}
        >
          Copy summary
        </button>
        {!canCopy && (
          <p className="text-sm text-ink-muted">
            {copyHint(allocation === null, pending)}
          </p>
        )}
        {copied && canCopy && (
          <p role="status" className="text-sm">
            Copied
          </p>
        )}
        {fallbackText !== null && (
          <>
            <label htmlFor="summary-text" className="text-sm">
              Select and copy:
            </label>
            <textarea
              id="summary-text"
              readOnly
              rows={fallbackText.split("\n").length}
              className="rounded-md border-2 border-rule bg-paper p-2 font-mono text-sm"
              value={fallbackText}
              onFocus={(e) => e.currentTarget.select()}
            />
          </>
        )}
      </div>
    </div>
  );
}
