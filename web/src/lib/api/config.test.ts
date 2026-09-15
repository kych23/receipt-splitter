import { describe, expect, it, vi } from "vitest";
import { apiBaseUrl } from "./config";

describe("apiBaseUrl", () => {
  it("strips trailing slashes", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test///");
    expect(apiBaseUrl()).toBe("http://api.test");
  });

  it("throws when the variable is empty", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    expect(() => apiBaseUrl()).toThrow("NEXT_PUBLIC_API_BASE_URL is not set");
  });
});
