/**
 * Editor state for one receipt: pure reducer plus conversion to the API's save body.
 * See docs/design/slice-3-manual-split.md ("Editor state").
 */

import type {
  ParsedReceipt,
  ReceiptLine,
  ReceiptResponse,
  SaveReceiptRequest,
  TaxLine,
} from "./api/receipts";
import { newId } from "./ids";
import { centsToInput, parseDollars } from "./money";

export const MAX_LINES = 300;
export const MAX_PEOPLE = 20;
export const MAX_PERSON_NAME = 40;
export const MAX_ITEM_NAME = 120;
export const TAX_INVALID = "tax";

export type ItemDraft = {
  lineId: string;
  name: string;
  priceInput: string;
  taxable: boolean | null;
  /** Printed tax code kept from the server; cleared when `taxable` changes. */
  taxCode: string | null;
  /** Other ReceiptLine fields (raw_text, quantity, unit_price_cents), sent back unchanged. */
  passthrough: Partial<ReceiptLine>;
};

export type Person = { key: string; name: string };

export type EditorState = {
  base: Omit<ParsedReceipt, "lines" | "tax_lines">;
  items: ItemDraft[];
  /** Discount, fee and deposit lines, passed through unchanged. */
  readOnlyLines: ReceiptLine[];
  taxInput: string;
  taxLabel: string;
  /** Non-null when the server content had 2+ tax lines; the tax field is then read-only. */
  extraTaxLines: TaxLine[] | null;
  people: Person[];
  /** lineId -> person keys in people order. A key is absent, never []. */
  tags: Record<string, string[]>;
  /** Local changes not yet acknowledged by a save. */
  dirty: boolean;
  /** Incremented by every local change; a save acknowledges the revision it sent. */
  revision: number;
};

export type ItemPatch = {
  name?: string;
  priceInput?: string;
  taxable?: boolean;
};

export type Action =
  | { type: "addItem" }
  | { type: "updateItem"; lineId: string; patch: ItemPatch }
  | { type: "removeItem"; lineId: string }
  | { type: "setTax"; input: string }
  | { type: "addPerson"; name: string }
  | { type: "removePerson"; key: string }
  | { type: "toggleTag"; lineId: string; key: string }
  | { type: "loadFromServer"; receipt: ReceiptResponse }
  | { type: "markSaved"; revision: number };

const DEFAULT_TAX_LABEL = "Tax";

function codePoints(text: string): number {
  return [...text].length;
}

function blankItem(): ItemDraft {
  return {
    lineId: newId(),
    name: "",
    priceInput: "",
    taxable: null,
    taxCode: null,
    passthrough: {},
  };
}

export function isBlankItem(item: ItemDraft): boolean {
  return item.name.trim() === "" && item.priceInput.trim() === "";
}

export function initialState(): EditorState {
  return {
    base: { currency: "USD" },
    items: [],
    readOnlyLines: [],
    taxInput: "",
    taxLabel: DEFAULT_TAX_LABEL,
    extraTaxLines: null,
    people: [],
    tags: {},
    dirty: false,
    revision: 0,
  };
}

/** The printed subtotal and total no longer describe a receipt whose prices were edited. */
function clearPrintedTotals(base: EditorState["base"]): EditorState["base"] {
  return { ...base, subtotal_cents: null, total_cents: null };
}

function withoutKey(
  tags: Record<string, string[]>,
  lineId: string,
): Record<string, string[]> {
  const next = { ...tags };
  delete next[lineId];
  return next;
}

function fromServer(receipt: ReceiptResponse): EditorState {
  const { lines, tax_lines: taxLines, ...base } = receipt.content;
  const items: ItemDraft[] = [];
  const readOnlyLines: ReceiptLine[] = [];
  for (const line of lines) {
    if (line.kind !== "item") {
      readOnlyLines.push(line);
      continue;
    }
    items.push({
      lineId: line.line_id,
      name: line.name,
      priceInput: centsToInput(line.total_cents),
      taxable: line.taxable ?? null,
      taxCode: line.tax_code ?? null,
      passthrough: {
        raw_text: line.raw_text,
        quantity: line.quantity,
        unit_price_cents: line.unit_price_cents,
        discount_target_line_id: line.discount_target_line_id,
      },
    });
  }
  if (items.length === 0 && readOnlyLines.length < MAX_LINES)
    items.push(blankItem());

  let taxInput = "";
  let taxLabel = DEFAULT_TAX_LABEL;
  let extraTaxLines: TaxLine[] | null = null;
  if (taxLines.length === 1) {
    taxInput = centsToInput(taxLines[0].amount_cents);
    taxLabel = taxLines[0].label;
  } else if (taxLines.length > 1) {
    extraTaxLines = taxLines;
    taxInput = centsToInput(
      taxLines.reduce((sum, t) => sum + t.amount_cents, 0),
    );
  }

  return {
    base,
    items,
    readOnlyLines,
    taxInput,
    taxLabel,
    extraTaxLines,
    people: receipt.participants.map((p) => ({
      key: p.key,
      name: p.display_name,
    })),
    tags: { ...receipt.assignments },
    dirty: false,
    revision: 0,
  };
}

function applyEdit(
  state: EditorState,
  action: Exclude<Action, { type: "loadFromServer" | "markSaved" }>,
): EditorState {
  switch (action.type) {
    case "addItem": {
      if (state.items.length + state.readOnlyLines.length >= MAX_LINES)
        return state;
      return {
        ...state,
        items: [...state.items, blankItem()],
        base: clearPrintedTotals(state.base),
      };
    }
    case "updateItem": {
      const { patch } = action;
      const priceChanged = patch.priceInput !== undefined;
      return {
        ...state,
        base: priceChanged ? clearPrintedTotals(state.base) : state.base,
        items: state.items.map((item) => {
          if (item.lineId !== action.lineId) return item;
          const next = { ...item, ...patch };
          if (patch.taxable !== undefined && patch.taxable !== item.taxable)
            next.taxCode = null;
          return next;
        }),
      };
    }
    case "removeItem":
      return {
        ...state,
        base: clearPrintedTotals(state.base),
        items: state.items.filter((item) => item.lineId !== action.lineId),
        readOnlyLines: state.readOnlyLines.filter(
          (line) =>
            !(
              line.kind === "discount" &&
              line.discount_target_line_id === action.lineId
            ),
        ),
        tags: withoutKey(state.tags, action.lineId),
      };
    case "setTax":
      if (state.extraTaxLines !== null) return state;
      return {
        ...state,
        taxInput: action.input,
        base: clearPrintedTotals(state.base),
      };
    case "addPerson":
      if (addPersonError(state, action.name) !== null) return state;
      return {
        ...state,
        people: [...state.people, { key: newId(), name: action.name.trim() }],
      };
    case "removePerson": {
      const tags: Record<string, string[]> = {};
      for (const [lineId, keys] of Object.entries(state.tags)) {
        const kept = keys.filter((k) => k !== action.key);
        if (kept.length > 0) tags[lineId] = kept;
      }
      return {
        ...state,
        people: state.people.filter((p) => p.key !== action.key),
        tags,
      };
    }
    case "toggleTag": {
      const current = state.tags[action.lineId] ?? [];
      const selected = new Set(current);
      if (selected.has(action.key)) selected.delete(action.key);
      else selected.add(action.key);
      const ordered = state.people
        .map((p) => p.key)
        .filter((k) => selected.has(k));
      const tags =
        ordered.length === 0
          ? withoutKey(state.tags, action.lineId)
          : { ...state.tags, [action.lineId]: ordered };
      return { ...state, tags };
    }
  }
}

export function reducer(state: EditorState, action: Action): EditorState {
  if (action.type === "loadFromServer") return fromServer(action.receipt);
  if (action.type === "markSaved") {
    return action.revision === state.revision
      ? { ...state, dirty: false }
      : state;
  }
  const next = applyEdit(state, action);
  if (next === state) return state;
  return { ...next, dirty: true, revision: state.revision + 1 };
}

/** Why `name` can't be added as a person, or null if it can. */
export function addPersonError(
  state: EditorState,
  name: string,
): string | null {
  const trimmed = name.trim();
  if (trimmed === "") return "Enter a name";
  const folded = trimmed.toLowerCase();
  if (state.people.some((p) => p.name.trim().toLowerCase() === folded))
    return "Already added";
  if (codePoints(trimmed) > MAX_PERSON_NAME)
    return `Up to ${MAX_PERSON_NAME} characters`;
  if (state.people.length >= MAX_PEOPLE) return `Up to ${MAX_PEOPLE} people`;
  return null;
}

/** Item and deposit lines (excluding blank rows) that nobody is tagged on yet. */
export function untaggedCount(state: EditorState): number {
  const items = state.items.filter(
    (i) => !isBlankItem(i) && !state.tags[i.lineId],
  );
  const deposits = state.readOnlyLines.filter(
    (l) => l.kind === "deposit" && !state.tags[l.line_id],
  );
  return items.length + deposits.length;
}

/** The save body for the current state, or the ids of rows (and "tax") that need fixing first. */
export function toSaveBody(
  state: EditorState,
): { body: SaveReceiptRequest } | { invalid: string[] } {
  const invalid: string[] = [];
  const itemLines: ReceiptLine[] = [];
  const skipped = new Set<string>();

  for (const item of state.items) {
    if (isBlankItem(item)) {
      skipped.add(item.lineId);
      continue;
    }
    const name = item.name.trim();
    const cents = parseDollars(item.priceInput);
    const nameLength = codePoints(name);
    if (nameLength < 1 || nameLength > MAX_ITEM_NAME || cents === null) {
      invalid.push(item.lineId);
      continue;
    }
    itemLines.push({
      raw_text: "",
      ...item.passthrough,
      line_id: item.lineId,
      kind: "item",
      name,
      total_cents: cents,
      taxable: item.taxable,
      tax_code: item.taxCode,
    });
  }

  let taxLines: TaxLine[];
  if (state.extraTaxLines !== null) {
    taxLines = state.extraTaxLines;
  } else if (state.taxInput.trim() === "") {
    taxLines = [];
  } else {
    const taxCents = parseDollars(state.taxInput);
    if (taxCents === null) {
      invalid.push(TAX_INVALID);
      taxLines = [];
    } else {
      taxLines =
        taxCents === 0
          ? []
          : [{ label: state.taxLabel, amount_cents: taxCents }];
    }
  }

  if (invalid.length > 0) return { invalid };

  const assignments: Record<string, string[]> = {};
  for (const [lineId, keys] of Object.entries(state.tags)) {
    if (!skipped.has(lineId) && keys.length > 0) assignments[lineId] = keys;
  }

  return {
    body: {
      content: {
        ...state.base,
        lines: [...itemLines, ...state.readOnlyLines],
        tax_lines: taxLines,
      },
      participants: state.people.map((p) => ({
        key: p.key,
        display_name: p.name,
      })),
      assignments,
    },
  };
}
