import { describe, expect, it } from "vitest";

import { executionScopeLine } from "@/lib/executionScopeLine";

const LINKING = "Linking changes selections, never execution authority.";
const UNAVAILABLE =
  "Unavailable · Session mode couldn't be confirmed. Sign in again or reload.";

describe("executionScopeLine", () => {
  it("names Example only for the example claim", () => {
    expect(executionScopeLine({ app: "terminal", mode: "explore", account: null })).toBe(
      `Example · No execution account selected · ${LINKING}`,
    );
    expect(executionScopeLine({ app: "portfolio", mode: "explore", account: "DH1" })).toBe(
      "Example · DH1",
    );
  });

  it("names Practice and Live from the claim", () => {
    expect(executionScopeLine({ app: "terminal", mode: "practice", account: null })).toBe(
      `Practice · No execution account selected · ${LINKING}`,
    );
    expect(executionScopeLine({ app: "terminal", mode: "live", account: "ACC" })).toBe(
      `Live · ACC · ${LINKING}`,
    );
  });

  it("gives an unconfirmed session its own copy and never calls it Example or Sample", () => {
    const line = executionScopeLine({ app: "terminal", mode: "unavailable", account: null });
    expect(line).toBe(`${UNAVAILABLE} · ${LINKING}`);
    expect(line).not.toMatch(/Example|Sample/);
    expect(executionScopeLine({ app: "portfolio", mode: "unavailable", account: "DH1" })).toBe(
      UNAVAILABLE,
    );
  });

  it("keeps the testing line independent of the session claim", () => {
    expect(executionScopeLine({ app: "testing", mode: "unavailable", account: null })).toBe(
      "Testing · Practice research scope only. Terminal account and Live authority are unchanged.",
    );
  });
});
