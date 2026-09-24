/**
 * Dollar-string <-> integer-cents conversion. Strings are parsed digit by digit, never with
 * parseFloat, so "4.89" is always exactly 489 cents.
 */

const DOLLARS_PATTERN = /^(\d{1,5})(?:\.(\d{1,2}))?$/;
const MINUS = "−";

/** Parse a user-typed price ("4.89", "$4.8", "4") into cents, or null if it isn't a valid price. */
export function parseDollars(input: string): number | null {
  let text = input.trim();
  if (text.startsWith("$")) text = text.slice(1).trim();
  const match = DOLLARS_PATTERN.exec(text);
  if (match === null) return null;
  const [, whole, frac = ""] = match;
  return Number(whole) * 100 + Number(frac.padEnd(2, "0"));
}

function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** 489 -> "$4.89", -200 -> "−$2.00", 123456 -> "$1,234.56". */
export function formatCents(cents: number): string {
  const sign = cents < 0 ? MINUS : "";
  const abs = Math.abs(cents);
  const dollars = groupThousands(String(Math.floor(abs / 100)));
  const rest = String(abs % 100).padStart(2, "0");
  return `${sign}$${dollars}.${rest}`;
}

/** Cents as an editable input value: 489 -> "4.89", 400 -> "4.00". */
export function centsToInput(cents: number): string {
  return formatCents(cents).replace("$", "").replaceAll(",", "");
}
