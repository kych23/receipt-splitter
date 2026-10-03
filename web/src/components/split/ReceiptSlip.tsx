"use client";

import { formatCents } from "@/lib/money";
import {
  type Action,
  type EditorState,
  type ItemDraft,
  type ItemPatch,
  MAX_ITEM_NAME,
  MAX_LINES,
  TAX_INVALID,
} from "@/lib/receipt-state";
import { input } from "./styles";
import { TagChips } from "./TagChips";

type Props = {
  state: EditorState;
  invalid: ReadonlySet<string>;
  isExample: boolean;
  dispatch: (action: Action) => void;
};

function TaxedToggle({
  label,
  taxable,
  onChange,
}: {
  label: string;
  taxable: boolean | null;
  onChange: (taxable: boolean) => void;
}): React.JSX.Element {
  const option = (value: boolean, text: string) => (
    <button
      type="button"
      aria-pressed={taxable === value}
      onClick={() => onChange(value)}
      className={`min-h-11 min-w-12 px-3 font-semibold first:rounded-l-full last:rounded-r-full ${
        taxable === value ? "bg-ink text-paper" : "text-ink"
      }`}
    >
      {text}
    </button>
  );
  return (
    <div
      role="group"
      aria-label={`Is ${label} taxed?`}
      className="flex items-center gap-2"
    >
      <span className="text-sm text-ink-muted">Taxed?</span>
      {/* No overflow-hidden: it would clip the buttons' focus outline. */}
      <span className="flex rounded-full border-2 border-rule">
        {option(true, "Yes")}
        {option(false, "No")}
      </span>
    </div>
  );
}

function ItemRow({
  item,
  index,
  state,
  invalid,
  dispatch,
}: {
  item: ItemDraft;
  index: number;
  state: EditorState;
  invalid: boolean;
  dispatch: Props["dispatch"];
}): React.JSX.Element {
  const label = item.name.trim() || `item ${index + 1}`;
  const errorId = `error-${item.lineId}`;
  const update = (patch: ItemPatch) =>
    dispatch({ type: "updateItem", lineId: item.lineId, patch });
  return (
    <li
      className="rule-dashed flex flex-col gap-3 py-4 first:border-t-0"
      data-invalid={invalid || undefined}
    >
      <div className="flex items-center gap-2">
        <label className="sr-only" htmlFor={`name-${item.lineId}`}>
          Item {index + 1} name
        </label>
        <input
          id={`name-${item.lineId}`}
          className={`${input(invalid)} min-w-0 flex-1`}
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? errorId : undefined}
          placeholder="Item"
          value={item.name}
          maxLength={MAX_ITEM_NAME}
          onChange={(e) => update({ name: e.target.value })}
        />
        <label className="sr-only" htmlFor={`price-${item.lineId}`}>
          Item {index + 1} price
        </label>
        <input
          id={`price-${item.lineId}`}
          className={`${input(invalid)} w-24 text-right font-mono`}
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? errorId : undefined}
          placeholder="0.00"
          inputMode="decimal"
          autoComplete="off"
          value={item.priceInput}
          onChange={(e) => update({ priceInput: e.target.value })}
        />
      </div>
      {invalid && (
        <p id={errorId} className="text-sm text-danger">
          Needs a name and a price like 4.99
        </p>
      )}
      <div className="flex items-center justify-between gap-2">
        <TaxedToggle
          label={label}
          taxable={item.taxable}
          onChange={(taxable) => update({ taxable })}
        />
        <button
          type="button"
          className="min-h-11 min-w-11 rounded-full text-xl text-ink-muted"
          aria-label={`Remove ${label}`}
          onClick={() => dispatch({ type: "removeItem", lineId: item.lineId })}
        >
          ×
        </button>
      </div>
      {state.people.length > 0 && (
        <TagChips
          label={label}
          people={state.people}
          selected={state.tags[item.lineId] ?? []}
          onToggle={(key) =>
            dispatch({ type: "toggleTag", lineId: item.lineId, key })
          }
        />
      )}
    </li>
  );
}

/** The receipt as a thermal-paper slip: items, who had them, and the printed tax. */
export function ReceiptSlip({
  state,
  invalid,
  isExample,
  dispatch,
}: Props): React.JSX.Element {
  const atCap = state.items.length + state.readOnlyLines.length >= MAX_LINES;
  const title = state.base.merchant_name?.trim() || "New receipt";
  const taxInvalid = invalid.has(TAX_INVALID);

  return (
    <section aria-labelledby="slip-title" className="slip mb-3 px-4 pt-5 pb-6">
      <header className="flex items-baseline justify-between gap-3 pb-3">
        <h2 id="slip-title" className="font-mono text-xl font-semibold">
          {title}
        </h2>
        {isExample && (
          <p className="-rotate-3 rounded border-2 border-pen px-2 text-sm font-bold text-pen">
            Example receipt
          </p>
        )}
      </header>
      {state.people.length === 0 && (
        <p className="pb-2 text-sm text-ink-muted">
          Add the people splitting this receipt above, then tap who had each
          item.
        </p>
      )}

      <ul className="rule-dashed">
        {state.items.map((item, index) => (
          <ItemRow
            key={item.lineId}
            item={item}
            index={index}
            state={state}
            invalid={invalid.has(item.lineId)}
            dispatch={dispatch}
          />
        ))}
        {state.readOnlyLines.map((line) => (
          <li
            key={line.line_id}
            className="rule-dashed flex flex-col gap-3 py-4"
          >
            <p className="flex justify-between font-mono">
              <span>{line.name}</span>
              <span>{formatCents(line.total_cents)}</span>
            </p>
            {line.kind === "deposit" && state.people.length > 0 && (
              <TagChips
                label={line.name}
                people={state.people}
                selected={state.tags[line.line_id] ?? []}
                onToggle={(key) =>
                  dispatch({ type: "toggleTag", lineId: line.line_id, key })
                }
              />
            )}
          </li>
        ))}
      </ul>

      <button
        type="button"
        className="mt-1 min-h-11 w-full rounded-md border-2 border-dashed border-rule font-semibold text-pen disabled:opacity-40"
        disabled={atCap}
        onClick={() => dispatch({ type: "addItem" })}
      >
        + Add item
      </button>

      <div className="rule-dashed mt-5 flex items-center justify-between gap-3 pt-4">
        <div>
          <label htmlFor="tax-input" className="font-mono font-semibold">
            Tax on receipt
          </label>
          <p id="tax-hint" className="text-sm text-ink-muted">
            {state.extraTaxLines !== null
              ? "Multiple tax lines"
              : "Type the tax printed on your receipt"}
          </p>
          {taxInvalid && (
            <p id="tax-error" className="text-sm text-danger">
              Enter the tax like 1.23
            </p>
          )}
        </div>
        <input
          id="tax-input"
          aria-describedby={taxInvalid ? "tax-hint tax-error" : "tax-hint"}
          aria-invalid={taxInvalid || undefined}
          className={`${input(taxInvalid)} w-24 text-right font-mono`}
          placeholder="0.00"
          inputMode="decimal"
          autoComplete="off"
          value={state.taxInput}
          readOnly={state.extraTaxLines !== null}
          onChange={(e) => dispatch({ type: "setTax", input: e.target.value })}
        />
      </div>
    </section>
  );
}
