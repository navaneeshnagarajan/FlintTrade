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

  it("gives Live an execution-mode line that does not claim a session is open", () => {
    expect(modeHonestyCopy("live")).toBe(
      "Live — real-money capable when a broker is Connected. Orders place only on a live session.",
    );
  });

  it("keeps the three lines distinct", () => {
    const lines = new Set(Object.values(MODE_HONESTY_COPY));
    expect(lines.size).toBe(3);
  });
});
