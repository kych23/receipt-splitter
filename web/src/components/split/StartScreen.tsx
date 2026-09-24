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
    <section className="flex flex-col gap-4 py-6">
      {notice && <p className="font-medium">{notice}</p>}
      <p>
        Type in a receipt, add who&apos;s splitting it, tap items to people, and
        get exact totals.
      </p>
      <div className="flex flex-col gap-3">
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
      </div>
      {error && (
        <p role="alert" className="text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
    </section>
  );
}
