import { describe, expect, it } from "vitest";
import { centsToInput, formatCents, parseDollars } from "./money";

describe("parseDollars", () => {
  it.each([
    ["4.89", 489],
    ["4", 400],
    ["4.8", 480],
    ["$4.89", 489],
    [" 4.89 ", 489],
    ["$ 4.89", 489],
    ["0", 0],
    ["0.00", 0],
    ["007", 700],
    ["99999.99", 9999999],
  ])("parses %j as %i cents", (input, cents) => {
    expect(parseDollars(input)).toBe(cents);
  });

  it.each([
    "",
    " ",
    "-1",
    "4.891",
    "4.",
    ".5",
    "1,000.00",
    "abc",
    "100000",
    "$",
    "4.8.9",
  ])("rejects %j", (input) => {
    expect(parseDollars(input)).toBeNull();
  });
});

describe("formatCents", () => {
  it.each([
    [489, "$4.89"],
    [-200, "−$2.00"],
    [0, "$0.00"],
    [5, "$0.05"],
    [123456, "$1,234.56"],
    [100000000, "$1,000,000.00"],
  ])("formats %i as %j", (cents, text) => {
    expect(formatCents(cents)).toBe(text);
  });
});

describe("centsToInput", () => {
  it.each([
    [489, "4.89"],
    [400, "4.00"],
    [5, "0.05"],
    [123456, "1234.56"],
  ])("formats %i as %j", (cents, text) => {
    expect(centsToInput(cents)).toBe(text);
  });

  it("round-trips through parseDollars", () => {
    for (const cents of [0, 1, 99, 100, 489, 9999999]) {
      expect(parseDollars(centsToInput(cents))).toBe(cents);
    }
  });
});
