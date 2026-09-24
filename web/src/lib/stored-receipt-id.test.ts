import { act, renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  resetStoredReceiptIdForTests,
  setStoredReceiptId,
  useStoredReceiptId,
} from "./stored-receipt-id";

describe("stored receipt id", () => {
  beforeEach(() => {
    window.localStorage.clear();
    resetStoredReceiptIdForTests();
  });
  afterEach(() => resetStoredReceiptIdForTests());

  it("round-trips through localStorage", () => {
    window.localStorage.setItem("receiptsplit.receiptId", "abc");
    const { result } = renderHook(() => useStoredReceiptId());
    expect(result.current).toBe("abc");
    act(() => setStoredReceiptId("def"));
    expect(result.current).toBe("def");
    expect(window.localStorage.getItem("receiptsplit.receiptId")).toBe("def");
    act(() => setStoredReceiptId(null));
    expect(result.current).toBeNull();
    expect(window.localStorage.getItem("receiptsplit.receiptId")).toBeNull();
  });

  it("works in memory when storage throws", () => {
    const blocked = () => {
      throw new DOMException("blocked", "SecurityError");
    };
    const getItem = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(blocked);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(blocked);
    const { result } = renderHook(() => useStoredReceiptId());
    expect(result.current).toBeNull();
    expect(getItem).toHaveBeenCalled();
    act(() => setStoredReceiptId("x"));
    expect(result.current).toBe("x");
  });

  it("server snapshot is undefined", () => {
    let seen: unknown = "unset";
    function Probe() {
      seen = useStoredReceiptId();
      return null;
    }
    renderToString(createElement(Probe));
    expect(seen).toBeUndefined();
  });
});
