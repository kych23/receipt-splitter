import { describe, expect, it } from "vitest";
import { PERSON_COLORS, personColor, personInitial } from "./person-colors";

function luminance(hex: string): number {
  const channels = [1, 3, 5].map(
    (i) => parseInt(hex.slice(i, i + 2), 16) / 255,
  );
  const [r, g, b] = channels.map((c) =>
    c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

describe("person colours", () => {
  it("every colour carries white text at WCAG AA (4.5:1)", () => {
    for (const color of PERSON_COLORS) {
      expect(1.05 / (luminance(color) + 0.05)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("cycles after eight people", () => {
    expect(personColor(0)).toBe(personColor(8));
    expect(new Set(PERSON_COLORS.map((_, i) => personColor(i))).size).toBe(8);
  });

  it.each([
    ["alex", "A"],
    ["  sam ", "S"],
    ["Émile", "É"],
    ["😀 Joy", "😀"],
    ["🇺🇸 Sam", "🇺🇸"],
    ["👩‍🍳 Chef", "👩‍🍳"],
    ["e\u0301mile", "E\u0301"],
    ["", "?"],
  ])("initial of %j is %j", (name, initial) => {
    expect(personInitial(name)).toBe(initial);
  });
});
