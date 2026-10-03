import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  AllocationProblemCode,
  AllocationWarning,
} from "@/lib/api/receipts";
import type { SaveStatus } from "@/lib/autosave";
import {
  EXAMPLE_PEOPLE,
  EXAMPLE_TOTALS,
  emptyReceipt,
  exampleReceipt,
} from "@/test/fixtures";
import { TotalsBar } from "./TotalsBar";

function bar({
  receipt = exampleReceipt(),
  dirty = false,
  status = { kind: "idle" } as SaveStatus,
  untagged = 0,
  onRetry = () => {},
  onOpen = () => {},
} = {}) {
  return render(
    <TotalsBar
      receipt={receipt}
      people={EXAMPLE_PEOPLE}
      onOpen={onOpen}
      dirty={dirty}
      status={status}
      untagged={untagged}
      onRetry={onRetry}
    />,
  );
}

const totals = () => screen.getByRole("region", { name: "Totals" });

describe("TotalsBar", () => {
  it("shows each person's total", () => {
    bar();
    expect(totals()).toHaveTextContent(EXAMPLE_TOTALS);
  });

  it("shows two people then '+1 more' for three, so large totals still fit", () => {
    const receipt = exampleReceipt();
    for (const p of receipt.allocation!.participants) p.total_cents = 12345;
    bar({ receipt });
    expect(totals()).toHaveTextContent(
      /Alex\s*\$123\.45.*Sam\s*\$123\.45.*\+1 more/,
    );
    expect(totals()).not.toHaveTextContent("Jordan");
  });

  it("keeps '+K more' outside the clipped people and unshrinkable", () => {
    const receipt = exampleReceipt();
    for (const p of receipt.allocation!.participants) p.total_cents = 123456;
    bar({ receipt });
    const more = screen.getByText("+1 more");
    const people = screen.getByTestId("totals-people");
    expect(people).toHaveClass("overflow-hidden");
    expect(people).not.toContainElement(more);
    expect(more).toHaveClass("shrink-0");
  });

  it("stays one row: beyond three people it shows two plus '+K more'", () => {
    const receipt = exampleReceipt();
    const extra = (id: string) => ({
      ...receipt.allocation!.participants[0],
      participant_id: id,
    });
    receipt.allocation!.participants.push(
      extra("00000000-0000-4000-8000-000000000004"),
    );
    bar({ receipt });
    expect(totals()).toHaveTextContent("+2 more");
    expect(totals()).toHaveTextContent(/Alex\s*\$4\.26/);
    expect(totals()).not.toHaveTextContent("Jordan");
  });

  it("Details opens the breakdown", () => {
    const onOpen = vi.fn();
    bar({ onOpen });
    const details = screen.getByRole("button", { name: /Details/ });
    expect(details).toHaveAttribute("aria-haspopup", "dialog");
    fireEvent.click(details);
    expect(onOpen).toHaveBeenCalledOnce();
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
    else expect(totals()).not.toHaveTextContent(/Mark every item|Tax entered/);
  });

  it("says Saving… while dirty, without fading the totals", () => {
    bar({ dirty: true });
    expect(screen.getByRole("status")).toHaveTextContent("Saving…");
    expect(
      screen.getByRole("button", { name: /Details/ }).className,
    ).not.toMatch(/opacity/);
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
