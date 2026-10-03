"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  createReceipt,
  deleteReceipt,
  getReceipt,
  type ReceiptResponse,
  saveReceipt,
} from "@/lib/api/receipts";
import { Autosaver, type SaveStatus } from "@/lib/autosave";
import { initialState, reducer, untaggedCount } from "@/lib/receipt-state";
import {
  setStoredReceiptId,
  useStoredReceiptId,
} from "@/lib/stored-receipt-id";
import { PeopleEditor } from "./PeopleEditor";
import { ReceiptSlip } from "./ReceiptSlip";
import { StartScreen } from "./StartScreen";
import { Summary } from "./Summary";
import { button, dangerButton } from "./styles";
import { TotalsBar } from "./TotalsBar";
import { TotalsSheet } from "./TotalsSheet";

type ExitHandler = (notice: string | null) => void;

const NO_INVALID: ReadonlySet<string> = new Set();

function ReceiptEditor({
  id,
  initialReceipt,
  onExit,
}: {
  id: string;
  initialReceipt: ReceiptResponse;
  onExit: ExitHandler;
}): React.JSX.Element {
  const [state, dispatch] = useReducer(reducer, initialReceipt, (receipt) =>
    reducer(initialState(), { type: "loadFromServer", receipt }),
  );
  const [serverReceipt, setServerReceipt] = useState(initialReceipt);
  const [status, setStatus] = useState<SaveStatus>({ kind: "idle" });
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  // The saver reads the latest state through a ref, updated after each render.
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  });

  // One saver per mounted editor; created in an effect so StrictMode's remount gets a fresh one.
  const saverRef = useRef<Autosaver | null>(null);
  useEffect(() => {
    const saver = new Autosaver({
      receiptId: id,
      save: saveReceipt,
      create: () => createReceipt(false),
      getState: () => stateRef.current,
      onSaved: (receipt, revision) => {
        setServerReceipt(receipt);
        dispatch({ type: "markSaved", revision });
      },
      // Remember the replacement so a refresh reopens it; the editor stays mounted.
      onRecreated: (receipt) => setStoredReceiptId(receipt.id),
      onStatus: setStatus,
    });
    saverRef.current = saver;
    return () => {
      saver.cancel();
      saverRef.current = null;
    };
  }, [id]);

  useEffect(() => {
    if (state.dirty) saverRef.current?.edited();
  }, [state.dirty, state.revision]);

  const currentId = () => saverRef.current?.receiptId ?? id;

  async function handleDelete(): Promise<void> {
    saverRef.current?.cancel();
    setDeleteError(null);
    try {
      await deleteReceipt(currentId());
    } catch {
      setDeleteError("Couldn't delete — try again");
      if (stateRef.current.dirty) saverRef.current?.edited();
      return;
    }
    onExit(null);
  }

  async function handleStartNew(): Promise<void> {
    saverRef.current?.cancel();
    try {
      await deleteReceipt(currentId());
    } catch {
      // Best effort: the row expires on its own.
    }
    onExit(null);
  }

  const invalid =
    status.kind === "invalid" ? new Set(status.lineIds) : NO_INVALID;
  const stale = state.dirty || status.kind === "invalid";

  return (
    <div className="flex flex-col gap-6">
      <PeopleEditor state={state} dispatch={dispatch} />
      <ReceiptSlip
        state={state}
        invalid={invalid}
        isExample={serverReceipt.is_example}
        dispatch={dispatch}
      />
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={button}
          onClick={() => void handleStartNew()}
        >
          Start a new receipt
        </button>
        <button
          type="button"
          className={dangerButton}
          onClick={() => void handleDelete()}
        >
          Delete receipt
        </button>
      </div>
      {deleteError && (
        <p role="alert" className="text-danger">
          {deleteError}
        </p>
      )}
      <TotalsBar
        receipt={serverReceipt}
        people={state.people}
        dirty={state.dirty}
        status={status}
        untagged={untaggedCount(state)}
        onRetry={() => saverRef.current?.retryNow()}
        onOpen={() => setSheetOpen(true)}
      />
      <TotalsSheet open={sheetOpen} onClose={() => setSheetOpen(false)}>
        <Summary
          receipt={serverReceipt}
          state={state}
          stale={stale}
          dirty={state.dirty}
          status={status}
          onRetry={() => saverRef.current?.retryNow()}
        />
      </TotalsSheet>
    </div>
  );
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; receipt: ReceiptResponse };

function ReceiptLoader(props: {
  id: string;
  initial: ReceiptResponse | null;
  onExit: ExitHandler;
}): React.JSX.Element {
  // Fixed at mount: if the saver later moves the edits to a replacement receipt, the stored id
  // changes but this editor must neither refetch nor remount.
  const [id] = useState(props.id);
  const [initial] = useState(props.initial);
  const { onExit } = props;
  const [load, setLoad] = useState<LoadState>(
    initial ? { kind: "ready", receipt: initial } : { kind: "loading" },
  );
  const [attempt, setAttempt] = useState(0);
  const skipFetch = initial !== null && attempt === 0;

  useEffect(() => {
    if (skipFetch) return;
    let cancelled = false;
    async function run(): Promise<void> {
      try {
        const receipt = await getReceipt(id);
        if (cancelled) return;
        if (receipt === null) onExit("This receipt expired");
        else setLoad({ kind: "ready", receipt });
      } catch {
        if (!cancelled) setLoad({ kind: "error" });
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [id, attempt, skipFetch, onExit]);

  if (load.kind === "loading") return <p role="status">Loading…</p>;
  if (load.kind === "error") {
    return (
      <div className="flex flex-col gap-3 py-6">
        <p role="alert">Can&apos;t reach ReceiptSplit</p>
        <button
          type="button"
          className={button}
          onClick={() => {
            setLoad({ kind: "loading" });
            setAttempt((n) => n + 1);
          }}
        >
          Retry
        </button>
        {/* A load that keeps failing (e.g. a stored row the API can no longer read) must not
            trap the user until the receipt expires. */}
        <button type="button" className={button} onClick={() => onExit(null)}>
          Start a new receipt
        </button>
      </div>
    );
  }
  return (
    <ReceiptEditor id={id} initialReceipt={load.receipt} onExit={onExit} />
  );
}

/** The whole splitting flow: start screen, or the stored receipt's editor. */
export function SplitApp(): React.JSX.Element {
  const storedId = useStoredReceiptId();
  const [notice, setNotice] = useState<string | null>(null);
  const [created, setCreated] = useState<ReceiptResponse | null>(null);
  // Keys the editor. Not the stored id: that changes when the saver recreates an expired receipt,
  // and remounting then would throw away the edits it is saving.
  const [session, setSession] = useState(0);

  const exit = useCallback<ExitHandler>((message) => {
    setNotice(message);
    setCreated(null);
    setSession((n) => n + 1);
    setStoredReceiptId(null);
  }, []);

  const started = useCallback((receipt: ReceiptResponse) => {
    setNotice(null);
    setCreated(receipt);
    setSession((n) => n + 1);
    setStoredReceiptId(receipt.id);
  }, []);

  // Server render and first client render: storage hasn't been read yet.
  if (storedId === undefined) return <p role="status">Loading…</p>;
  if (storedId === null)
    return <StartScreen notice={notice} onStarted={started} />;
  return (
    <ReceiptLoader
      key={session}
      id={storedId}
      initial={created?.id === storedId ? created : null}
      onExit={exit}
    />
  );
}
