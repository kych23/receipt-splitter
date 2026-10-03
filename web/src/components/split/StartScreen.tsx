"use client";

import { useState } from "react";
import {
  ApiError,
  createReceipt,
  type ReceiptResponse,
} from "@/lib/api/receipts";
import { button, primaryButton } from "./styles";

function createErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) {
    const minutes = Math.max(1, Math.ceil((error.retryAfterS ?? 60) / 60));
    return `Too many new receipts from this network — try again in ${minutes} min`;
  }
  if (error instanceof ApiError && error.status === 503) {
    return "ReceiptSplit is busy — try again in a few minutes";
  }
  return "Can't reach ReceiptSplit — try again";
}

type Props = {
  notice: string | null;
  onStarted: (receipt: ReceiptResponse) => void;
};

export function StartScreen({ notice, onStarted }: Props): React.JSX.Element {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start(example: boolean): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      onStarted(await createReceipt(example));
    } catch (e) {
      setError(createErrorMessage(e));
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="start-title" className="flex flex-col gap-8 pt-2">
      <div className="flex flex-col gap-3">
        <h2 id="start-title" className="text-3xl leading-tight font-bold">
          Split a grocery receipt to the cent.
        </h2>
        <p className="text-lg text-ink-muted">
          Type in the items, tap who had what, and see what everyone owes. Tax
          is charged only on the items that were taxed.
        </p>
      </div>

      {/* Decorative: a sample of what the app produces. */}
      <div
        aria-hidden
        className="slip mx-2 -rotate-1 px-5 pt-4 pb-5 font-mono text-sm"
      >
        <p className="pb-2 font-semibold">TARGET</p>
        <p className="rule-dashed flex justify-between pt-2">
          <span>Cheetos</span>
          <span>4.89</span>
        </p>
        <p className="flex justify-between">
          <span>Kitsch</span>
          <span>9.99 T</span>
        </p>
        <p className="flex justify-between">
          <span>Slime Mart</span>
          <span>5.00 T</span>
        </p>
        <p className="rule-dashed mt-2 flex justify-between pt-2 font-semibold">
          <span>Sam owes</span>
          <span>15.03</span>
        </p>
      </div>

      <div className="flex flex-col gap-3">
        {notice && <p className="font-semibold">{notice}</p>}
        <button
          type="button"
          className={primaryButton}
          disabled={busy}
          onClick={() => void start(false)}
        >
          Start a new receipt
        </button>
        <button
          type="button"
          className={button}
          disabled={busy}
          onClick={() => void start(true)}
        >
          Try an example
        </button>
        {error && (
          <p role="alert" className="text-danger">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}
