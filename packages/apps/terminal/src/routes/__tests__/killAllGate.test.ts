import { describe, expect, it } from "vitest";
import {
  RISK_RUNTIME_UNAVAILABLE_HELPER,
  killAllArmed,
  killAllHelper,
  resolveRiskLoadState,
  type KillAllGateInput,
} from "../killAllGate";

function gate(
  overrides: Partial<KillAllGateInput> & Pick<KillAllGateInput, "mode">,
): KillAllGateInput {
  return {
    riskLoadState: "ready",
    hasManagedAccounts: true,
    ...overrides,
  };
}

describe("killAllGate (FT-DITTO-003)", () => {
  it("locks the helper copy verbatim", () => {
    expect(RISK_RUNTIME_UNAVAILABLE_HELPER).toBe(
      "Risk runtime unavailable — Kill All disabled.",
    );
  });

  it("always disarms Explore, even with a ready snapshot and accounts", () => {
    const input = gate({ mode: "explore" });
    expect(killAllArmed(input)).toBe(false);
    expect(killAllHelper(input)).toBe(RISK_RUNTIME_UNAVAILABLE_HELPER);
  });

  it("uses the runtime helper as the single reason when Explore has no accounts", () => {
    expect(killAllHelper(gate({ mode: "explore", hasManagedAccounts: false }))).toBe(
      RISK_RUNTIME_UNAVAILABLE_HELPER,
    );
  });

  it("keeps the Explore helper while risk is pending or failed", () => {
    expect(killAllHelper(gate({ mode: "explore", riskLoadState: "loading" }))).toBe(
      RISK_RUNTIME_UNAVAILABLE_HELPER,
    );
    expect(killAllHelper(gate({ mode: "explore", riskLoadState: "error" }))).toBe(
      RISK_RUNTIME_UNAVAILABLE_HELPER,
    );
    expect(killAllArmed(gate({ mode: "explore", riskLoadState: "error" }))).toBe(false);
  });

  it("disarms Practice and Live when the risk runtime is unavailable", () => {
    for (const mode of ["practice", "live"] as const) {
      const failed = gate({ mode, riskLoadState: "error" });
      expect(killAllArmed(failed)).toBe(false);
      expect(killAllHelper(failed)).toBe(RISK_RUNTIME_UNAVAILABLE_HELPER);

      const pending = gate({ mode, riskLoadState: "loading" });
      expect(killAllArmed(pending)).toBe(false);
      expect(killAllHelper(pending)).toBe(RISK_RUNTIME_UNAVAILABLE_HELPER);
    }
  });

  it("disarms a successful empty snapshot without the runtime helper (FT-DITTO-001)", () => {
    const empty = gate({ mode: "live", hasManagedAccounts: false });
    expect(killAllArmed(empty)).toBe(false);
    expect(killAllHelper(empty)).toBeNull();
  });

  it("arms Live and Practice only with a live runtime and managed accounts", () => {
    expect(killAllArmed(gate({ mode: "live" }))).toBe(true);
    expect(killAllHelper(gate({ mode: "live" }))).toBeNull();
    expect(killAllArmed(gate({ mode: "practice" }))).toBe(true);
    expect(killAllHelper(gate({ mode: "practice" }))).toBeNull();
  });

  it("treats a successful snapshot as ready and pending/failed fetches as unavailable", () => {
    expect(resolveRiskLoadState({ risk: { accounts: [] }, isError: false })).toBe("ready");
    expect(resolveRiskLoadState({ risk: { accounts: [{ id: "a" }] }, isError: false })).toBe(
      "ready",
    );
    expect(resolveRiskLoadState({ risk: undefined, isError: false })).toBe("loading");
    expect(resolveRiskLoadState({ risk: null, isError: false })).toBe("loading");
    expect(resolveRiskLoadState({ risk: undefined, isError: true })).toBe("error");
    expect(resolveRiskLoadState({ risk: { accounts: [] }, isError: true })).toBe("ready");
  });
});
