"use client";

import { useState } from "react";
import {
  type Action,
  addPersonError,
  type EditorState,
} from "@/lib/receipt-state";
import { button, input, sectionTitle } from "./styles";

type Props = {
  state: EditorState;
  dispatch: (action: Action) => void;
};

export function PeopleEditor({ state, dispatch }: Props): React.JSX.Element {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  function add(event: React.FormEvent): void {
    event.preventDefault();
    const problem = addPersonError(state, name);
    setError(problem);
    if (problem !== null) return;
    dispatch({ type: "addPerson", name });
    setName("");
  }

  return (
    <section aria-labelledby="people-title" className="flex flex-col gap-2">
      <h2 id="people-title" className={sectionTitle}>
        People
      </h2>
      {state.people.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {state.people.map((person) => (
            <li
              key={person.key}
              className="flex items-center rounded-full border border-neutral-300 pl-4 dark:border-neutral-700"
            >
              <span>{person.name}</span>
              <button
                type="button"
                className="min-h-11 min-w-11 text-lg"
                aria-label={`Remove ${person.name}`}
                onClick={() =>
                  dispatch({ type: "removePerson", key: person.key })
                }
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="flex gap-2" onSubmit={add} noValidate>
        <label htmlFor="person-name" className="sr-only">
          Person&apos;s name
        </label>
        <input
          id="person-name"
          className={`${input} min-w-0 flex-1`}
          placeholder="Name"
          autoComplete="off"
          value={name}
          aria-invalid={error !== null || undefined}
          aria-describedby={error ? "person-error" : undefined}
          onChange={(e) => {
            setName(e.target.value);
            setError(null);
          }}
        />
        <button type="submit" className={button}>
          Add
        </button>
      </form>
      {error && (
        <p
          id="person-error"
          role="alert"
          className="text-sm text-red-700 dark:text-red-400"
        >
          {error}
        </p>
      )}
    </section>
  );
}
