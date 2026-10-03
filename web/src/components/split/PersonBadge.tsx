import { personColor, personInitial } from "@/lib/person-colors";

const NEUTRAL = "#5c6066"; // white text at 6:1

/** Coloured initial for a person. Decorative: always rendered next to the name or in a labelled control. */
export function PersonBadge({
  name,
  index,
}: {
  name: string;
  /** Position in the local people list; null for someone no longer in it (shown neutral). */
  index: number | null;
}): React.JSX.Element {
  return (
    <span
      aria-hidden
      className="inline-flex size-7 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white"
      style={{ backgroundColor: index === null ? NEUTRAL : personColor(index) }}
    >
      {personInitial(name)}
    </span>
  );
}
