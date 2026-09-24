/** Shared Tailwind class strings. Every tap target is at least 44 px tall (min-h-11). */
export const button =
  "min-h-11 rounded-lg border border-neutral-300 px-4 font-medium disabled:opacity-40 dark:border-neutral-700";
export const primaryButton =
  "min-h-11 rounded-lg bg-neutral-900 px-4 font-medium text-white disabled:opacity-40 dark:bg-neutral-100 dark:text-neutral-900";
export const input =
  "min-h-11 rounded-lg border border-neutral-300 bg-transparent px-3 dark:border-neutral-700";
export const invalidInput =
  "border-red-600 ring-1 ring-red-600 dark:border-red-500";
export const chip = (pressed: boolean) =>
  `min-h-11 rounded-full border px-4 ${
    pressed
      ? "border-neutral-900 bg-neutral-900 text-white dark:border-neutral-100 dark:bg-neutral-100 dark:text-neutral-900"
      : "border-neutral-300 dark:border-neutral-700"
  }`;
export const sectionTitle = "text-lg font-semibold";
