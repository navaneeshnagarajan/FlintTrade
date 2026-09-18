import { describe, expect, it } from "vitest";
import {
  EXPLORE_MIRROR_START_HELPER,
  MIRROR_START_CONNECT_HELPER,
  MIRROR_START_SELECT_HELPER,
  mirrorStartArmed,
  mirrorStartHelper,
} from "../mirrorStartGate";

describe("mirrorStartGate (FT-DITTO-002)", () => {
  it("always disarms Explore, even with source, targets, and accounts", () => {
    const input = {
      mode: "explore" as const,
      sourceAccount: "acc_1",
      targetCount: 2,
      activeAccountCount: 3,
    };
    expect(mirrorStartArmed(input)).toBe(false);
    expect(mirrorStartHelper(input)).toBe(EXPLORE_MIRROR_START_HELPER);
  });

  it("uses the Explore helper as the single reason when Explore has no accounts", () => {
    expect(
      mirrorStartHelper({
        mode: "explore",
        sourceAccount: "",
        targetCount: 0,
        activeAccountCount: 0,
      }),
    ).toBe(EXPLORE_MIRROR_START_HELPER);
  });

  it("asks to connect accounts when Practice/Live have none", () => {
    for (const mode of ["practice", "live"] as const) {
      const input = {
        mode,
        sourceAccount: "",
        targetCount: 0,
        activeAccountCount: 0,
      };
      expect(mirrorStartArmed(input)).toBe(false);
      expect(mirrorStartHelper(input)).toBe(MIRROR_START_CONNECT_HELPER);
    }
  });

  it("asks to select source and a target when accounts exist but the pair is incomplete", () => {
    expect(
      mirrorStartHelper({
        mode: "practice",
        sourceAccount: "",
        targetCount: 0,
        activeAccountCount: 2,
      }),
    ).toBe(MIRROR_START_SELECT_HELPER);
    expect(
      mirrorStartHelper({
        mode: "live",
        sourceAccount: "acc_1",
        targetCount: 0,
        activeAccountCount: 2,
      }),
    ).toBe(MIRROR_START_SELECT_HELPER);
    expect(
      mirrorStartArmed({
        mode: "practice",
        sourceAccount: "",
        targetCount: 1,
        activeAccountCount: 2,
      }),
    ).toBe(false);
  });

  it("arms only in Practice/Live with source, ≥1 target, and accounts ready", () => {
    for (const mode of ["practice", "live"] as const) {
      const input = {
        mode,
        sourceAccount: "acc_1",
        targetCount: 1,
        activeAccountCount: 2,
      };
      expect(mirrorStartArmed(input)).toBe(true);
      expect(mirrorStartHelper(input)).toBeNull();
    }
  });
});
