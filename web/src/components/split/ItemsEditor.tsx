"use client";

import type { ReceiptLine } from "@/lib/api/receipts";
import { formatCents } from "@/lib/money";
import {
  type Action,
  type ItemDraft,
  type ItemPatch,
  MAX_ITEM_NAME,
  MAX_LINES,
} from "@/lib/receipt-state";
import { button, chip, input, invalidInput, sectionTitle } from "./styles";

type Props = {
  items: ItemDraft[];
  readOnlyLines: ReceiptLine[];
  invalid: ReadonlySet<string>;
  dispatch: (action: Action) => void;
};

function ItemRow({
  item,
  index,
  invalid,
  dispatch,
}: {
  item: ItemDraft;
  index: number;
  invalid: boolean;
  dispatch: Props["dispatch"];
}) {
  const label = item.name.trim() || `item ${index + 1}`;
  const update = (patch: ItemPatch) =>
    dispatch({ type: "updateItem", lineId: item.lineId, patch });
  return (
    <li
      className={`flex flex-wrap items-center gap-2 rounded-lg p-2 ${invalid ? invalidInput : ""}`}
      data-invalid={invalid || undefined}
    >
      <label className="sr-only" htmlFor={`name-${item.lineId}`}>
        Item {index + 1} name
      </label>
      <input
        id={`name-${item.lineId}`}
        className={`${input} min-w-0 flex-1 basis-40`}
        placeholder="Item"
        value={item.name}
        maxLength={MAX_ITEM_NAME}
        onChange={(e) => update({ name: e.target.value })}
      />
      <label className="sr-only" htmlFor={`price-${item.lineId}`}>
        Item {index + 1} price
      </label>
      <div className="flex items-center gap-1">
        <span aria-hidden>$</span>
        <input
          id={`price-${item.lineId}`}
          className={`${input} w-24`}
          placeholder="0.00"
          inputMode="decimal"
          autoComplete="off"
          value={item.priceInput}
          onChange={(e) => update({ priceInput: e.target.value })}
        />
      </div>
      <div
        role="group"
        aria-label={`Is ${label} taxed?`}
        className="flex items-center gap-1"
      >
        <span className="text-sm">Taxed?</span>
        <button
          type="button"
          className={chip(item.taxable === true)}
          aria-pressed={item.taxable === true}
          onClick={() => update({ taxable: true })}
        >
          Yes
        </button>
        <button
          type="button"
          className={chip(item.taxable === false)}
          aria-pressed={item.taxable === false}
          onClick={() => update({ taxable: false })}
        >
          No
        </button>
      </div>
      <button
        type="button"
        className="min-h-11 min-w-11 text-xl"
        aria-label={`Remove ${label}`}
        onClick={() => dispatch({ type: "removeItem", lineId: item.lineId })}
      >
        ×
      </button>
    </li>
  );
}

export function ItemsEditor({
  items,
  readOnlyLines,
  invalid,
  dispatch,
}: Props): React.JSX.Element {
  const atCap = items.length + readOnlyLines.length >= MAX_LINES;
  return (
    <section aria-labelledby="items-title" className="flex flex-col gap-2">
      <h2 id="items-title" className={sectionTitle}>
        Items
      </h2>
      <ul className="flex flex-col gap-1">
        {items.map((item, index) => (
          <ItemRow
            key={item.lineId}
            item={item}
            index={index}
            invalid={invalid.has(item.lineId)}
            dispatch={dispatch}
          />
        ))}
      </ul>
      {readOnlyLines.length > 0 && (
        <ul className="flex flex-col gap-1 px-2 text-sm">
          {readOnlyLines.map((line) => (
            <li key={line.line_id} className="flex justify-between">
              <span>{line.name}</span>
              <span>{formatCents(line.total_cents)}</span>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        className={button}
        disabled={atCap}
        onClick={() => dispatch({ type: "addItem" })}
      >
        + Add item
      </button>
    </section>
  );
}
