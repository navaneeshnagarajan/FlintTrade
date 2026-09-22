import { describe, expect, it } from "vitest";
import { MODE_HONESTY_COPY, modeHonestyCopy } from "../modeHonesty";

describe("mode honesty copy", () => {
  it("gives Explore its sample-desk line", () => {
    expect(modeHonestyCopy("explore")).toBe(
      "Explore — sample data only. No broker session, no live orders.",
    );
  });

  it("gives Practice its sandbox line", () => {
    expect(modeHonestyCopy("practice")).toBe(
      "Practice — SandboxEngine fills. Not your funded broker account.",
    );
  });

  it("gives Live its funded-session line", () => {
    expect(modeHonestyCopy("live")).toBe(
      "Live — real broker session. Orders and money move for real.",
    );
  });

  it("keeps the three lines distinct", () => {
    const lines = new Set(Object.values(MODE_HONESTY_COPY));
    expect(lines.size).toBe(3);
  });
});
