"use client";

import { personColor } from "@/lib/person-colors";
import type { Person } from "@/lib/receipt-state";
import { PersonBadge } from "./PersonBadge";

type Props = {
  label: string;
  people: Person[];
  selected: readonly string[];
  onToggle: (key: string) => void;
};

/** One toggle per person for a line. Pressed = filled in the person's colour plus a check mark. */
export function TagChips({
  label,
  people,
  selected,
  onToggle,
}: Props): React.JSX.Element {
  const chosen = new Set(selected);
  return (
    <div
      role="group"
      aria-label={`Who had ${label}`}
      className="flex flex-wrap gap-2"
    >
      {people.map((person, index) => {
        const pressed = chosen.has(person.key);
        return (
          <button
            key={person.key}
            type="button"
            aria-pressed={pressed}
            onClick={() => onToggle(person.key)}
            className={`flex min-h-11 items-center gap-1.5 rounded-full border-2 py-1 pr-3 pl-1 font-sans text-sm font-semibold ${
              pressed
                ? "border-[var(--chip-ring)] text-white"
                : "border-rule text-ink"
            }`}
            style={
              pressed ? { backgroundColor: personColor(index) } : undefined
            }
          >
            <PersonBadge name={person.name} index={index} />
            {person.name}
            {pressed && <span aria-hidden>✓</span>}
          </button>
        );
      })}
    </div>
  );
}
