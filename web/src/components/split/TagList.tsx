"use client";

import { formatCents, parseDollars } from "@/lib/money";
import {
  type Action,
  type EditorState,
  isBlankItem,
} from "@/lib/receipt-state";
import { chip, sectionTitle } from "./styles";

type Props = {
  state: EditorState;
  dispatch: (action: Action) => void;
};

type Taggable = { lineId: string; name: string; price: string };

function taggableLines(state: EditorState): Taggable[] {
  const items = state.items
    .filter((item) => !isBlankItem(item))
    .map((item) => {
      const cents = parseDollars(item.priceInput);
      return {
        lineId: item.lineId,
        name: item.name.trim() || "(unnamed item)",
        price: cents === null ? "" : formatCents(cents),
      };
    });
  const deposits = state.readOnlyLines
    .filter((line) => line.kind === "deposit")
    .map((line) => ({
      lineId: line.line_id,
      name: line.name,
      price: formatCents(line.total_cents),
    }));
  return [...items, ...deposits];
}

export function TagList({ state, dispatch }: Props): React.JSX.Element {
  const lines = taggableLines(state);
  let emptyHint: string | null = null;
  if (state.people.length === 0) emptyHint = "Add people to tag items.";
  else if (lines.length === 0) emptyHint = "Add an item to tag it.";

  return (
    <section aria-labelledby="tags-title" className="flex flex-col gap-2">
      <h2 id="tags-title" className={sectionTitle}>
        Who had what
      </h2>
      {emptyHint !== null ? (
        <p className="text-sm opacity-70">{emptyHint}</p>
      ) : (
        <>
          <p className="text-sm opacity-70">
            Tap everyone who shared an item — it splits evenly.
          </p>
          <ul className="flex flex-col gap-3">
            {lines.map((line) => {
              const selected = new Set(state.tags[line.lineId] ?? []);
              return (
                <li key={line.lineId} className="flex flex-col gap-1">
                  <p>
                    <span className="font-medium">{line.name}</span>{" "}
                    <span className="opacity-70">{line.price}</span>
                  </p>
                  <div
                    role="group"
                    aria-label={`Who had ${line.name}`}
                    className="flex flex-wrap gap-2"
                  >
                    {state.people.map((person) => (
                      <button
                        key={person.key}
                        type="button"
                        className={chip(selected.has(person.key))}
                        aria-pressed={selected.has(person.key)}
                        onClick={() =>
                          dispatch({
                            type: "toggleTag",
                            lineId: line.lineId,
                            key: person.key,
                          })
                        }
                      >
                        {person.name}
                      </button>
                    ))}
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
