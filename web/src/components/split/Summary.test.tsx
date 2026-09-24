import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { initialState, reducer } from "@/lib/receipt-state";
import { emptyReceipt, exampleReceipt } from "@/test/fixtures";
import { Summary } from "./Summary";

const EXPECTED_TEXT =
  "Target — $38.09\nAlex $4.26\nSam $15.03\nJordan $18.80\n(split with ReceiptSplit)";

function renderSummary({ stale = false, receipt = exampleReceipt() } = {}) {
  const state = reducer(initialState(), { type: "loadFromServer", receipt });
  return render(
    <Summary
      receipt={receipt}
      state={state}
      stale={stale}
      deleteError={null}
      onDelete={() => {}}
      onStartNew={() => {}}
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

  it("disables Copy while stale and dims amounts", () => {
    renderSummary({ stale: true });
    expect(copyButton()).toBeDisabled();
    expect(screen.getByText("Saving… copy when done")).toBeInTheDocument();
  });

  it("disables Copy without an allocation", () => {
    renderSummary({ receipt: emptyReceipt() });
    expect(copyButton()).toBeDisabled();
    expect(screen.getByText("Finish tagging to copy")).toBeInTheDocument();
  });
});
