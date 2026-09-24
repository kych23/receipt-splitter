"use client";

import { useState } from "react";
import type { ReceiptResponse } from "@/lib/api/receipts";
import { formatCents } from "@/lib/money";
import type { EditorState } from "@/lib/receipt-state";
import { summaryText } from "@/lib/summary-text";
import { button, primaryButton, sectionTitle } from "./styles";

type Props = {
  receipt: ReceiptResponse;
  state: EditorState;
  /** Local edits aren't reflected in `receipt` yet (unsaved or invalid). */
  stale: boolean;
  deleteError: string | null;
  onDelete: () => void;
  onStartNew: () => void;
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
    <li className="flex justify-between">
      <span>{label}</span>
      <span>{formatCents(cents)}</span>
    </li>
  );
}

export function Summary({
  receipt,
  state,
  stale,
  deleteError,
  onDelete,
  onStartNew,
}: Props): React.JSX.Element {
  const [fallbackText, setFallbackText] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const { allocation } = receipt;
  const names = lineNames(state);
  const people = new Map(
    receipt.participants.map((p) => [p.key, p.display_name]),
  );
  const canCopy = allocation !== null && !stale;

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
    <section aria-labelledby="summary-title" className="flex flex-col gap-3">
      <h2 id="summary-title" className={sectionTitle}>
        Summary
      </h2>
      {allocation && (
        <ul
          className={`flex flex-col gap-3 ${stale ? "opacity-50" : ""}`}
          aria-busy={stale}
        >
          {allocation.participants.map((person) => (
            <li
              key={person.participant_id}
              className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
            >
              <p className="flex justify-between font-semibold">
                <span>
                  {people.get(person.participant_id) ?? "(removed person)"}
                </span>
                <span>{formatCents(person.total_cents)}</span>
              </p>
              <ul className="mt-1 text-sm">
                {person.line_shares.map((share) => (
                  <li key={share.line_id} className="flex justify-between">
                    <span>
                      {names.get(share.line_id) ?? "(edited item)"}
                      {share.split_count > 1 && (
                        <span className="opacity-70">
                          {" "}
                          (split {share.split_count})
                        </span>
                      )}
                    </span>
                    <span>{formatCents(share.share_cents)}</span>
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
          ))}
        </ul>
      )}
      <div className="flex flex-col gap-1">
        <button
          type="button"
          className={primaryButton}
          disabled={!canCopy}
          onClick={() => void copy()}
        >
          Copy summary
        </button>
        {!canCopy && (
          <p className="text-sm opacity-70">
            {allocation === null
              ? "Finish tagging to copy"
              : "Saving… copy when done"}
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
              className="rounded-lg border border-neutral-300 p-2 font-mono text-sm dark:border-neutral-700"
              value={fallbackText}
              onFocus={(e) => e.currentTarget.select()}
            />
          </>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={button} onClick={onDelete}>
          Delete receipt
        </button>
        <button type="button" className={button} onClick={onStartNew}>
          Start a new receipt
        </button>
      </div>
      {deleteError && (
        <p role="alert" className="text-red-700 dark:text-red-400">
          {deleteError}
        </p>
      )}
    </section>
  );
}
