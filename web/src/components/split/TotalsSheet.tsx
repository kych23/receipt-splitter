"use client";

import { useEffect, useRef } from "react";

type Props = {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
};

/**
 * Bottom sheet on a native modal <dialog>: the browser traps focus, closes on Esc and restores
 * focus to the opener. Children render only while open, so closed content is never in the
 * accessibility tree.
 */
export function TotalsSheet({
  open,
  onClose,
  children,
}: Props): React.JSX.Element {
  const ref = useRef<HTMLDialogElement>(null);
  const pressedBackdrop = useRef(false);

  useEffect(() => {
    const dialog = ref.current;
    if (dialog === null) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="sheet"
      aria-labelledby="sheet-title"
      onClose={onClose}
      onPointerDown={(event) => {
        pressedBackdrop.current = event.target === event.currentTarget;
      }}
      onClick={(event) => {
        // A tap on the backdrop lands on the <dialog> itself, outside the panel. Require the press
        // to start there too: a text selection dragged out of the panel also "clicks" the dialog.
        if (event.target === event.currentTarget && pressedBackdrop.current) {
          onClose();
        }
        pressedBackdrop.current = false;
      }}
    >
      {open && (
        <div className="slip max-h-[85dvh] overflow-y-auto overscroll-contain rounded-t-2xl px-5 pt-4 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
          <div className="flex items-center justify-between gap-3 pb-2">
            <h2 id="sheet-title" className="font-mono text-xl font-semibold">
              Who owes what
            </h2>
            <button
              type="button"
              className="min-h-11 rounded-full px-4 font-semibold text-pen"
              onClick={onClose}
            >
              Close
            </button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}
