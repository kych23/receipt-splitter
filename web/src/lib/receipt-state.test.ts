import { describe, expect, it } from "vitest";
import {
  ALEX,
  emptyReceipt,
  exampleReceipt,
  JORDAN,
  SAM,
} from "@/test/fixtures";
import {
  type Action,
  addPersonError,
  type EditorState,
  initialState,
  MAX_LINES,
  reducer,
  TAX_INVALID,
  toSaveBody,
  untaggedCount,
} from "./receipt-state";

function run(state: EditorState, ...actions: Action[]): EditorState {
  return actions.reduce(reducer, state);
}

function loaded(receipt = exampleReceipt()): EditorState {
  return reducer(initialState(), { type: "loadFromServer", receipt });
}

function body(state: EditorState) {
  const result = toSaveBody(state);
  if (!("body" in result))
    throw new Error(`invalid: ${result.invalid.join(",")}`);
  return result.body;
}

function withItem(
  state: EditorState,
  name: string,
  price: string,
): EditorState {
  const next = reducer(state, { type: "addItem" });
  const lineId = next.items[next.items.length - 1].lineId;
  return reducer(next, {
    type: "updateItem",
    lineId,
    patch: { name, priceInput: price },
  });
}

describe("loadFromServer", () => {
  it("round-trips the example through toSaveBody to the same content", () => {
    const receipt = exampleReceipt();
    const state = loaded(receipt);
    expect(state.dirty).toBe(false);
    expect(state.items.map((i) => i.priceInput)).toEqual([
      "4.89",
      "11.12",
      "9.99",
      "4.63",
      "5.00",
    ]);
    expect(state.taxInput).toBe("2.46");
    const saved = body(state);
    expect(saved.content).toEqual(receipt.content);
    expect(saved.participants).toEqual(receipt.participants);
    expect(saved.assignments).toEqual(receipt.assignments);
  });

  it("gives an empty receipt one blank row without becoming dirty", () => {
    const state = loaded(emptyReceipt());
    expect(state.items).toHaveLength(1);
    expect(state.items[0]).toMatchObject({
      name: "",
      priceInput: "",
      taxable: null,
    });
    expect(state.dirty).toBe(false);
    expect(body(state).content.lines).toEqual([]);
  });

  it("makes the tax field read-only for multiple tax lines and sends them unchanged", () => {
    const taxLines = [
      { label: "State", amount_cents: 100 },
      { label: "County", amount_cents: 50 },
    ];
    const state = loaded(
      emptyReceipt({
        content: { currency: "USD", lines: [], tax_lines: taxLines },
      }),
    );
    expect(state.extraTaxLines).toEqual(taxLines);
    expect(state.taxInput).toBe("1.50");
    expect(reducer(state, { type: "setTax", input: "9" })).toBe(state);
    expect(body(state).content.tax_lines).toEqual(taxLines);
  });

  it("keeps non-item lines read-only and passthrough fields intact", () => {
    const receipt = emptyReceipt({
      content: {
        currency: "USD",
        merchant_name: "Wegmans",
        lines: [
          {
            line_id: "L1",
            kind: "item",
            raw_text: "SODA 12PK B",
            name: "Soda",
            quantity: "2",
            unit_price_cents: 599,
            total_cents: 1198,
            taxable: true,
            tax_code: "B",
          },
          {
            line_id: "D1",
            kind: "deposit",
            raw_text: "",
            name: "Deposit",
            total_cents: 60,
          },
        ],
        tax_lines: [],
      },
    });
    const state = loaded(receipt);
    expect(state.readOnlyLines.map((l) => l.line_id)).toEqual(["D1"]);
    expect(state.items[0].passthrough).toMatchObject({
      raw_text: "SODA 12PK B",
      quantity: "2",
      unit_price_cents: 599,
    });
    expect(body(state).content.lines).toEqual(receipt.content.lines);
  });
});

describe("edits", () => {
  it("addItem appends a blank row with taxable null and marks dirty", () => {
    const state = run(initialState(), { type: "addItem" });
    expect(state.items).toHaveLength(1);
    expect(state.items[0]).toMatchObject({
      name: "",
      priceInput: "",
      taxable: null,
      taxCode: null,
    });
    expect(state.dirty).toBe(true);
  });

  it("addItem is ignored at the line cap", () => {
    let state = initialState();
    for (let i = 0; i < MAX_LINES; i++)
      state = reducer(state, { type: "addItem" });
    expect(reducer(state, { type: "addItem" })).toBe(state);
  });

  it("price edits clear the printed subtotal and total; name edits do not", () => {
    const state = loaded();
    expect(state.base.total_cents).toBe(3809);
    const renamed = reducer(state, {
      type: "updateItem",
      lineId: "ex-1",
      patch: { name: "Chips" },
    });
    expect(renamed.base.total_cents).toBe(3809);
    const repriced = reducer(state, {
      type: "updateItem",
      lineId: "ex-1",
      patch: { priceInput: "5" },
    });
    expect(repriced.base.total_cents).toBeNull();
    expect(repriced.base.subtotal_cents).toBeNull();
    expect(
      reducer(state, { type: "setTax", input: "3" }).base.total_cents,
    ).toBeNull();
    expect(
      reducer(state, { type: "removeItem", lineId: "ex-1" }).base.total_cents,
    ).toBeNull();
  });

  it("changing taxable clears the printed tax code", () => {
    const state = run(loaded(), {
      type: "updateItem",
      lineId: "ex-1",
      patch: { taxable: true },
    });
    expect(state.items[0]).toMatchObject({ taxable: true, taxCode: null });
  });

  it("removeItem drops its tags and discounts that target it", () => {
    const receipt = emptyReceipt({
      content: {
        currency: "USD",
        lines: [
          {
            line_id: "L1",
            kind: "item",
            raw_text: "",
            name: "A",
            total_cents: 500,
          },
          {
            line_id: "D1",
            kind: "discount",
            raw_text: "",
            name: "Coupon",
            total_cents: -100,
            discount_target_line_id: "L1",
          },
          {
            line_id: "D2",
            kind: "discount",
            raw_text: "",
            name: "Store coupon",
            total_cents: -50,
          },
        ],
        tax_lines: [],
      },
      participants: [{ key: ALEX, display_name: "Alex" }],
      assignments: { L1: [ALEX] },
    });
    const state = run(loaded(receipt), { type: "removeItem", lineId: "L1" });
    expect(state.readOnlyLines.map((l) => l.line_id)).toEqual(["D2"]);
    expect(state.tags).toEqual({});
  });

  it("toggleTag keeps people order and deletes emptied entries", () => {
    let state = run(
      loaded(emptyReceipt()),
      { type: "addPerson", name: "Alex" },
      { type: "addPerson", name: "Sam" },
    );
    const [alex, sam] = state.people.map((p) => p.key);
    const lineId = state.items[0].lineId;
    state = run(
      state,
      { type: "toggleTag", lineId, key: sam },
      { type: "toggleTag", lineId, key: alex },
    );
    expect(state.tags[lineId]).toEqual([alex, sam]);
    state = run(
      state,
      { type: "toggleTag", lineId, key: alex },
      { type: "toggleTag", lineId, key: sam },
    );
    expect(lineId in state.tags).toBe(false);
  });

  it("removePerson removes their tags and deletes entries that become empty", () => {
    const state = run(loaded(), { type: "removePerson", key: JORDAN });
    expect(state.people.map((p) => p.name)).toEqual(["Alex", "Sam"]);
    expect(state.tags["ex-2"]).toBeUndefined();
    expect(state.tags["ex-4"]).toBeUndefined();
    expect(state.tags["ex-5"]).toEqual([ALEX, SAM]);
    for (const keys of Object.values(state.tags))
      expect(keys.length).toBeGreaterThan(0);
  });

  it("addPerson trims and is a no-op when invalid", () => {
    const state = run(initialState(), { type: "addPerson", name: "  Alex " });
    expect(state.people.map((p) => p.name)).toEqual(["Alex"]);
    expect(reducer(state, { type: "addPerson", name: "alex" })).toBe(state);
  });

  it("markSaved clears dirty only for the current revision", () => {
    const edited = run(loaded(), { type: "setTax", input: "3" });
    const sentRevision = edited.revision;
    const editedAgain = reducer(edited, { type: "setTax", input: "4" });
    expect(
      reducer(editedAgain, { type: "markSaved", revision: sentRevision }).dirty,
    ).toBe(true);
    expect(
      reducer(edited, { type: "markSaved", revision: sentRevision }).dirty,
    ).toBe(false);
  });
});

describe("addPersonError", () => {
  it.each([
    ["", "Enter a name"],
    ["   ", "Enter a name"],
    [" ALEX ", "Already added"],
    ["x".repeat(41), "Up to 40 characters"],
    ["😀".repeat(40), null],
    ["Riley", null],
  ])("%j -> %j", (name, expected) => {
    const state = run(initialState(), { type: "addPerson", name: "Alex" });
    expect(addPersonError(state, name)).toBe(expected);
  });

  it("caps people at 20", () => {
    let state = initialState();
    for (let i = 0; i < 20; i++)
      state = reducer(state, { type: "addPerson", name: `P${i}` });
    expect(addPersonError(state, "One more")).toBe("Up to 20 people");
  });
});

describe("toSaveBody", () => {
  it("skips blank rows and drops their tags", () => {
    let state = run(loaded(emptyReceipt()), {
      type: "addPerson",
      name: "Alex",
    });
    const blank = state.items[0].lineId;
    state = reducer(state, {
      type: "toggleTag",
      lineId: blank,
      key: state.people[0].key,
    });
    const saved = body(state);
    expect(saved.content.lines).toEqual([]);
    expect(saved.assignments).toEqual({});
  });

  it("reports rows with a missing name or bad price", () => {
    let state = withItem(initialState(), "", "4.00");
    state = withItem(state, "Eggs", "4.891");
    state = withItem(state, "Milk", "3.49");
    const result = toSaveBody(state);
    expect(result).toEqual({
      invalid: [state.items[0].lineId, state.items[1].lineId],
    });
  });

  it("rejects item names over 120 code points", () => {
    const state = withItem(initialState(), "x".repeat(121), "1");
    expect(toSaveBody(state)).toEqual({ invalid: [state.items[0].lineId] });
  });

  it.each([
    ["", []],
    ["0", []],
    ["0.00", []],
    ["2.46", [{ label: "Tax", amount_cents: 246 }]],
  ])("tax %j -> %j", (input, expected) => {
    const state = run(initialState(), { type: "setTax", input });
    expect(body(state).content.tax_lines).toEqual(expected);
  });

  it("reports invalid tax as 'tax'", () => {
    const state = run(initialState(), { type: "setTax", input: "2.4.6" });
    expect(toSaveBody(state)).toEqual({ invalid: [TAX_INVALID] });
  });

  it("sends a typed item as kind item with trimmed name and cents", () => {
    let state = withItem(initialState(), "  Eggs ", "$10");
    state = reducer(state, {
      type: "updateItem",
      lineId: state.items[0].lineId,
      patch: { taxable: false },
    });
    expect(body(state).content.lines).toEqual([
      {
        raw_text: "",
        line_id: state.items[0].lineId,
        kind: "item",
        name: "Eggs",
        total_cents: 1000,
        taxable: false,
        tax_code: null,
      },
    ]);
  });
});

describe("untaggedCount", () => {
  it("counts untagged items and deposits, not blank rows", () => {
    let state = loaded(
      emptyReceipt({
        content: {
          currency: "USD",
          lines: [
            {
              line_id: "L1",
              kind: "item",
              raw_text: "",
              name: "Soda",
              total_cents: 599,
            },
            {
              line_id: "D1",
              kind: "deposit",
              raw_text: "",
              name: "Deposit",
              total_cents: 5,
            },
          ],
          tax_lines: [],
        },
      }),
    );
    state = reducer(state, { type: "addItem" });
    expect(untaggedCount(state)).toBe(2);
    state = run(state, { type: "addPerson", name: "Alex" });
    state = reducer(state, {
      type: "toggleTag",
      lineId: "D1",
      key: state.people[0].key,
    });
    expect(untaggedCount(state)).toBe(1);
    expect(untaggedCount(loaded())).toBe(0);
  });
});
