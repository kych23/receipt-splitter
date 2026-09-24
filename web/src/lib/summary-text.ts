import type { ReceiptResponse } from "./api/receipts";
import { formatCents } from "./money";

/** Plain-text split for pasting into a group chat, or null while there is no allocation. */
export function summaryText(receipt: ReceiptResponse): string | null {
  const { allocation } = receipt;
  if (allocation === null) return null;
  const totals = new Map(
    allocation.participants.map((p) => [p.participant_id, p.total_cents]),
  );
  const title = receipt.content.merchant_name?.trim() || "Receipt";
  const lines = [`${title} — ${formatCents(allocation.computed_total_cents)}`];
  for (const person of receipt.participants) {
    lines.push(
      `${person.display_name} ${formatCents(totals.get(person.key) ?? 0)}`,
    );
  }
  lines.push("(split with ReceiptSplit)");
  return lines.join("\n");
}
