import { describe, expect, it } from "vitest";
import { emptyReceipt, exampleReceipt } from "@/test/fixtures";
import { summaryText } from "./summary-text";

describe("summaryText", () => {
  it("formats the example", () => {
    expect(summaryText(exampleReceipt())).toBe(
      "Target — $38.09\nAlex $4.26\nSam $15.03\nJordan $18.80\n(split with ReceiptSplit)",
    );
  });

  it("falls back to 'Receipt' without a merchant name", () => {
    const receipt = exampleReceipt();
    receipt.content.merchant_name = null;
    expect(summaryText(receipt)?.split("\n")[0]).toBe("Receipt — $38.09");
  });

  it("is null without an allocation", () => {
    expect(summaryText(emptyReceipt())).toBeNull();
  });
});
