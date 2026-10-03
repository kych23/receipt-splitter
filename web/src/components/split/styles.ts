/** Shared Tailwind class strings. Every tap target is at least 44 px tall (min-h-11). */
const outlineButton =
  "min-h-11 rounded-full border-2 border-rule px-5 font-semibold disabled:opacity-40";
export const button = `${outlineButton} text-ink`;
export const dangerButton = `${outlineButton} text-danger`;
export const primaryButton =
  "min-h-11 rounded-full bg-pen px-5 font-semibold text-pen-contrast disabled:opacity-40";
/** Text input on paper. Border colour is chosen once by `invalid`: Tailwind v4 orders utilities
 * itself, so stacking `border-rule` and `border-danger` would not reliably let the second win. */
export const input = (invalid = false) =>
  `min-h-11 rounded-md border-2 bg-paper px-3 text-ink placeholder:text-ink-muted ${
    invalid ? "border-danger" : "border-rule"
  }`;
export const sectionTitle = "text-lg font-bold";
