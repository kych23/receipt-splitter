"use client";

import type { Action } from "@/lib/receipt-state";
import { input, invalidInput, sectionTitle } from "./styles";

type Props = {
  taxInput: string;
  readOnly: boolean;
  invalid: boolean;
  dispatch: (action: Action) => void;
};

export function TaxField({
  taxInput,
  readOnly,
  invalid,
  dispatch,
}: Props): React.JSX.Element {
  return (
    <section className="flex flex-col gap-1">
      <label htmlFor="tax-input" className={sectionTitle}>
        Tax on receipt
      </label>
      <div className="flex items-center gap-1">
        <span aria-hidden>$</span>
        <input
          id="tax-input"
          aria-describedby="tax-hint"
          aria-invalid={invalid || undefined}
          className={`${input} w-28 ${invalid ? invalidInput : ""}`}
          placeholder="0.00"
          inputMode="decimal"
          autoComplete="off"
          value={taxInput}
          readOnly={readOnly}
          onChange={(e) => dispatch({ type: "setTax", input: e.target.value })}
        />
      </div>
      <p id="tax-hint" className="text-sm opacity-70">
        {readOnly
          ? "Multiple tax lines"
          : "Type the tax printed on your receipt"}
      </p>
    </section>
  );
}
