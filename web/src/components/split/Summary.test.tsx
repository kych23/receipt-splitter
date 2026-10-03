import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SaveStatus } from "@/lib/autosave";
import { initialState, reducer } from "@/lib/receipt-state";
import { emptyReceipt, exampleReceipt } from "@/test/fixtures";
import { Summary } from "./Summary";

const EXPECTED_TEXT =
  "Target — $38.09\nAlex $4.26\nSam $15.03\nJordan $18.80\n(split with ReceiptSplit)";

type RenderOptions = {
  stale?: boolean;
  dirty?: boolean;
  status?: SaveStatus;
  receipt?: ReturnType<typeof exampleReceipt>;
  onRetry?: () => void;
};

function renderSummary({
  stale = false,
  dirty,
  status = { kind: "idle" },
  receipt = exampleReceipt(),
  onRetry = () => {},
}: RenderOptions = {}) {
  const state = reducer(initialState(), { type: "loadFromServer", receipt });
  return render(
    <Summary
      receipt={receipt}
      state={state}
      stale={stale}
      dirty={dirty ?? stale}
      status={status}
      onRetry={onRetry}
    />,
  );
}

function stubClipboard(writeText: unknown) {
  Object.defineProperty(navigator, "clipboard", {
    value: writeText === undefined ? undefined : { writeText },
    configurable: true,
  });
}

const copyButton = () => screen.getByRole("button", { name: "Copy summary" });
const fallback = () =>
  screen.queryByRole("textbox", { name: /select and copy/i });

describe("Summary", () => {
  it("shows each person's lines, tax and total", () => {
    renderSummary();
    expect(screen.getByText("Alex").closest("li")).toHaveTextContent(
      /Alex\$4\.26Cheetos \(split 2\)\$2\.45Slime Mart \(split 3\)\$1\.67Tax\$0\.14/,
    );
  });

  it("copies via the clipboard when available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    renderSummary();
    fireEvent.click(copyButton());
    expect(await screen.findByText("Copied")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(EXPECTED_TEXT);
    expect(fallback()).toBeNull();
  });

  it.each([
    ["clipboard API missing", undefined],
    [
      "writeText throws synchronously",
      () => {
        throw new Error("denied");
      },
    ],
    ["writeText rejects", () => Promise.reject(new Error("denied"))],
  ])("falls back to a textarea when the %s", async (_, writeText) => {
    stubClipboard(writeText);
    renderSummary();
    fireEvent.click(copyButton());
    const textarea = await screen.findByRole("textbox", {
      name: /select and copy/i,
    });
    expect(textarea).toHaveValue(EXPECTED_TEXT);
    expect(textarea).toHaveAttribute("readonly");
  });

  it("disables Copy while stale and says the totals are updating", () => {
    renderSummary({ stale: true });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Updating after your last edit…",
    );
    expect(copyButton()).toBeDisabled();
    expect(screen.getByText("Saving… copy when done")).toBeInTheDocument();
  });

  it("shows the real reason when no save is coming, not 'Updating'", () => {
    renderSummary({
      stale: true,
      dirty: true,
      status: { kind: "invalid", lineIds: ["x"] },
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Fix highlighted rows to update totals",
    );
    expect(screen.queryByText(/Updating|Saving…/)).toBeNull();
    expect(
      screen.getByText("Copy works once your changes are saved"),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("list")[0]).toHaveAttribute(
      "aria-busy",
      "false",
    );
  });

  it("offers Retry inside the sheet after saving gave up", () => {
    const onRetry = vi.fn();
    renderSummary({
      stale: true,
      dirty: true,
      status: { kind: "gave_up" },
      onRetry,
    });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("disables Copy without an allocation", () => {
    renderSummary({ receipt: emptyReceipt() });
    expect(copyButton()).toBeDisabled();
    expect(screen.getByText("Finish tagging to copy")).toBeInTheDocument();
  });
});
