import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** Reads the real colour tokens from globals.css so the WCAG claims there can't drift. */
// Vitest runs from web/ (under jsdom, import.meta.url is not a file: URL).
const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

function tokens(block: string): Record<string, string> {
  return Object.fromEntries(
    [...block.matchAll(/--([a-z-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [
      m[1],
      m[2],
    ]),
  );
}

const lightBlock = css.slice(
  css.indexOf(":root {"),
  css.indexOf("@media (prefers-color-scheme: dark)"),
);
const darkBlock = css.slice(
  css.indexOf("@media (prefers-color-scheme: dark)"),
  css.indexOf("@theme inline"),
);

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// [foreground, background, minimum ratio]
const PAIRS: [string, string, number][] = [
  ["ink", "paper", 4.5],
  ["ink", "page", 4.5],
  ["ink-muted", "paper", 4.5],
  ["ink-muted", "page", 4.5],
  ["pen", "paper", 4.5],
  ["pen", "page", 4.5],
  ["pen-contrast", "pen", 4.5],
  ["danger", "paper", 4.5],
  ["danger", "page", 4.5],
  ["paper", "ink", 4.5], // totals bar text
  ["rule", "paper", 3], // control borders (WCAG 1.4.11)
  ["rule", "page", 3],
  ["pen", "page", 3], // focus ring on the page
  ["paper", "ink", 3], // focus ring on the totals bar
];

describe.each([
  ["light", tokens(lightBlock)],
  ["dark", tokens(darkBlock)],
])("%s theme", (_, t) => {
  it.each(PAIRS)("%s on %s ≥ %d:1", (fg, bg, min) => {
    expect(t[fg], fg).toBeDefined();
    expect(t[bg], bg).toBeDefined();
    expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(min);
  });
});
