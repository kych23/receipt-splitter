/**
 * Marker colours for people, assigned by position in the people list. Each is dark enough for
 * white text at >= 4.5:1 in both themes. Colour is never the only cue: badges also show an
 * initial, and chips show the name and a check mark.
 */
export const PERSON_COLORS = [
  "#1f5fbf",
  "#b3261e",
  "#1e7b4f",
  "#8a3fb0",
  "#a35200",
  "#0f7685",
  "#b0306a",
  "#5b6100",
] as const;

export function personColor(index: number): string {
  return PERSON_COLORS[index % PERSON_COLORS.length];
}

const graphemes =
  typeof Intl !== "undefined" && "Segmenter" in Intl
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
    : null;

/** First user-perceived character (flag, emoji sequence, accented letter), upper-cased; "?" if blank. */
export function personInitial(name: string): string {
  const trimmed = name.trim();
  const first = graphemes
    ? graphemes.segment(trimmed)[Symbol.iterator]().next().value?.segment
    : Array.from(trimmed)[0];
  return first === undefined ? "?" : first.toLocaleUpperCase();
}
