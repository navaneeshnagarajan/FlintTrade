import { describe, expect, it } from "vitest";
import {
  EXPLORE_MIRROR_START_HELPER,
  MIRROR_START_CONNECT_HELPER,
  MIRROR_START_ERROR_HELPER,
  MIRROR_START_LOADING_HELPER,
  MIRROR_START_SELECT_HELPER,
  PRACTICE_MIRROR_START_HELPER,
  mirrorStartArmed,
  mirrorStartHelper,
  resolveAccountsLoadState,
  type MirrorStartGateInput,
} from "../mirrorStartGate";

function gate(
  overrides: Partial<MirrorStartGateInput> & Pick<MirrorStartGateInput, "mode">,
): MirrorStartGateInput {
  return {
    sourceAccount: "",
    targetCount: 0,
    activeAccountCount: 0,
    accountsLoadState: "ready",
    ...overrides,
  };
}

describe("mirrorStartGate (FT-DITTO-002)", () => {
  it("mutes Live mirror start with the incident rectify and leaves Explore on its own helper", () => {
    const live = gate({
      mode: "live",
      sourceAccount: "acc_1",
      targetCount: 1,
      activeAccountCount: 2,
      liveWriteBlock: "Wait for the exchange. FlintTrade cannot file a dispute.",
    });
    expect(mirrorStartArmed(live)).toBe(false);
    expect(mirrorStartHelper(live)).toContain("exchange");
    const explore = gate({
      mode: "explore",
      sourceAccount: "acc_1",
      targetCount: 1,
      activeAccountCount: 2,
      liveWriteBlock: "Wait for the exchange.",
    });
    expect(mirrorStartHelper(explore)).toBe(EXPLORE_MIRROR_START_HELPER);
  });

  it("always disarms Explore, even with source, targets, and accounts", () => {
    const input = gate({
      mode: "explore",
      sourceAccount: "acc_1",
      targetCount: 2,
      activeAccountCount: 3,
    });
    expect(mirrorStartArmed(input)).toBe(false);
    expect(mirrorStartHelper(input)).toBe(EXPLORE_MIRROR_START_HELPER);
  });

  it("uses the Explore helper as the single reason when Explore has no accounts", () => {
    expect(mirrorStartHelper(gate({ mode: "explore" }))).toBe(EXPLORE_MIRROR_START_HELPER);
  });

  it("keeps the Explore helper while accounts are pending or failed", () => {
    expect(
      mirrorStartHelper(gate({ mode: "explore", accountsLoadState: "loading" })),
    ).toBe(EXPLORE_MIRROR_START_HELPER);
    expect(
      mirrorStartHelper(gate({ mode: "explore", accountsLoadState: "error" })),
    ).toBe(EXPLORE_MIRROR_START_HELPER);
    expect(mirrorStartArmed(gate({ mode: "explore", accountsLoadState: "loading" }))).toBe(false);
  });

  it("always disarms Practice with the Live-only helper", () => {
    const ready = gate({
      mode: "practice",
      sourceAccount: "acc_1",
      targetCount: 1,
      activeAccountCount: 2,
    });
    expect(mirrorStartArmed(ready)).toBe(false);
    expect(mirrorStartHelper(ready)).toBe(PRACTICE_MIRROR_START_HELPER);
    expect(PRACTICE_MIRROR_START_HELPER).toBe(
      "Mirroring requires Live with broker accounts connected.",
    );
  });

  it("uses the Practice helper as the single reason when Practice has no accounts", () => {
    expect(mirrorStartHelper(gate({ mode: "practice" }))).toBe(PRACTICE_MIRROR_START_HELPER);
    expect(mirrorStartHelper(gate({ mode: "practice" }))).not.toBe(MIRROR_START_CONNECT_HELPER);
  });

  it("keeps the Practice helper while accounts are pending or failed", () => {
    expect(
      mirrorStartHelper(gate({ mode: "practice", accountsLoadState: "loading" })),
    ).toBe(PRACTICE_MIRROR_START_HELPER);
    expect(
      mirrorStartHelper(gate({ mode: "practice", accountsLoadState: "error" })),
    ).toBe(PRACTICE_MIRROR_START_HELPER);
  });

  it("asks to connect accounts only after Live successfully loads an empty list", () => {
    const input = gate({ mode: "live" });
    expect(mirrorStartArmed(input)).toBe(false);
    expect(mirrorStartHelper(input)).toBe(MIRROR_START_CONNECT_HELPER);
  });

  it("does not use the connect-accounts helper while Live accounts are pending or failed", () => {
    const loading = gate({ mode: "live", accountsLoadState: "loading" });
    expect(mirrorStartArmed(loading)).toBe(false);
    expect(mirrorStartHelper(loading)).toBe(MIRROR_START_LOADING_HELPER);
    expect(mirrorStartHelper(loading)).not.toBe(MIRROR_START_CONNECT_HELPER);

    const failed = gate({ mode: "live", accountsLoadState: "error" });
    expect(mirrorStartArmed(failed)).toBe(false);
    expect(mirrorStartHelper(failed)).toBe(MIRROR_START_ERROR_HELPER);
    expect(mirrorStartHelper(failed)).not.toBe(MIRROR_START_CONNECT_HELPER);
  });

  it("asks to select source and a target when Live accounts exist but the pair is incomplete", () => {
    expect(
      mirrorStartHelper(
        gate({
          mode: "live",
          sourceAccount: "",
          targetCount: 0,
          activeAccountCount: 2,
        }),
      ),
    ).toBe(MIRROR_START_SELECT_HELPER);
    expect(
      mirrorStartHelper(
        gate({
          mode: "live",
          sourceAccount: "acc_1",
          targetCount: 0,
          activeAccountCount: 2,
        }),
      ),
    ).toBe(MIRROR_START_SELECT_HELPER);
    expect(
      mirrorStartArmed(
        gate({
          mode: "live",
          sourceAccount: "",
          targetCount: 1,
          activeAccountCount: 2,
        }),
      ),
    ).toBe(false);
  });

  it("treats a successful list as ready and pending/failed fetches as not empty", () => {
    expect(resolveAccountsLoadState({ accounts: { accounts: [] }, isError: false })).toBe("ready");
    expect(resolveAccountsLoadState({ accounts: { accounts: [{ id: "a" }] }, isError: false })).toBe(
      "ready",
    );
    expect(resolveAccountsLoadState({ accounts: undefined, isError: false })).toBe("loading");
    expect(resolveAccountsLoadState({ accounts: undefined, isError: true })).toBe("error");
    expect(resolveAccountsLoadState({ accounts: { accounts: [] }, isError: true })).toBe("ready");
  });

  it("arms only in Live with source, ≥1 target, and accounts ready", () => {
    const live = gate({
      mode: "live",
      sourceAccount: "acc_1",
      targetCount: 1,
      activeAccountCount: 2,
    });
    expect(mirrorStartArmed(live)).toBe(true);
    expect(mirrorStartHelper(live)).toBeNull();

    expect(
      mirrorStartArmed(
        gate({
          mode: "practice",
          sourceAccount: "acc_1",
          targetCount: 1,
          activeAccountCount: 2,
        }),
      ),
    ).toBe(false);
  });
});
