import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  AllocationProblemCode,
  AllocationWarning,
} from "@/lib/api/receipts";
import type { SaveStatus } from "@/lib/autosave";
import { emptyReceipt, exampleReceipt } from "@/test/fixtures";
import { TotalsBar } from "./TotalsBar";

function bar({
  receipt = exampleReceipt(),
  dirty = false,
  status = { kind: "idle" } as SaveStatus,
  untagged = 0,
  onRetry = () => {},
} = {}) {
  return render(
    <TotalsBar
      receipt={receipt}
      dirty={dirty}
      status={status}
      untagged={untagged}
      onRetry={onRetry}
    />,
  );
}

const totals = () => screen.getByRole("contentinfo", { name: "Totals" });

describe("TotalsBar", () => {
  it("shows each person's total", () => {
    bar();
    expect(totals()).toHaveTextContent(
      "Alex $4.26 · Sam $15.03 · Jordan $18.80",
    );
  });

  it.each<[AllocationProblemCode, string]>([
    ["no_participants", "Add the people splitting this receipt"],
    ["unassigned_line", "Tag every item — 3 left"],
    ["no_assignable_lines", "Add an item"],
    ["negative_line_net", "Can't split yet — check the items"],
  ])("problem %s", (code, message) => {
    bar({
      receipt: emptyReceipt({ allocation_problem: { code, detail: "x" } }),
      untagged: 3,
    });
    expect(totals()).toHaveTextContent(message);
  });

  it.each<[AllocationWarning, string | null]>([
    ["unknown_taxability", "Mark every item taxed or not — tax may be off"],
    [
      "tax_fallback_proportional",
      "Mark every item taxed or not — tax may be off",
    ],
    ["tax_without_taxable_lines", "Tax entered but no item is marked taxed"],
    ["zero_base_equal_split", null],
  ])("warning %s", (warning, message) => {
    const receipt = exampleReceipt();
    receipt.allocation!.warnings = [warning];
    bar({ receipt });
    if (message) expect(totals()).toHaveTextContent(message);
    else expect(totals().querySelectorAll("p")).toHaveLength(1);
  });

  it("dims totals and says Saving… while dirty", () => {
    bar({ dirty: true });
    expect(screen.getByRole("status")).toHaveTextContent("Saving…");
    expect(screen.getByText(/Alex \$4\.26/)).toHaveClass("opacity-50");
  });

  it.each<[SaveStatus, string]>([
    [{ kind: "offline" }, "Offline — will retry"],
    [{ kind: "paused" }, "Saving paused — too many changes"],
    [
      { kind: "rejected" },
      "Couldn't save — something doesn't look right. Your edits are still here.",
    ],
    [
      { kind: "invalid", lineIds: ["x"] },
      "Fix highlighted rows to update totals",
    ],
  ])("save status replaces Saving… (%o)", (status, message) => {
    bar({ dirty: true, status });
    expect(screen.getByRole("status")).toHaveTextContent(message);
    expect(screen.getByRole("status")).not.toHaveTextContent("Saving…");
  });

  it("shows Retry after giving up", () => {
    const onRetry = vi.fn();
    bar({ dirty: true, status: { kind: "gave_up" }, onRetry });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
