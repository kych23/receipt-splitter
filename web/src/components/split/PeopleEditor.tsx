"use client";

import { useState } from "react";
import {
  type Action,
  addPersonError,
  type EditorState,
} from "@/lib/receipt-state";
import { PersonBadge } from "./PersonBadge";
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
    <section aria-labelledby="people-title" className="flex flex-col gap-3">
      <h2 id="people-title" className={sectionTitle}>
        Who&apos;s splitting
      </h2>
      {state.people.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {state.people.map((person, index) => (
            <li
              key={person.key}
              className="flex min-h-11 items-center gap-2 rounded-full bg-paper py-1 pl-2"
            >
              <PersonBadge name={person.name} index={index} />
              <span className="font-semibold">{person.name}</span>
              <button
                type="button"
                className="min-h-11 min-w-11 rounded-full text-xl text-ink-muted"
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
          className={`${input(error !== null)} min-w-0 flex-1`}
          placeholder="Add a name"
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
        <p id="person-error" role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </section>
  );
}
