/**
 * Sample-chain LTP used by Explore Options Builder (FT-LAB-003).
 *
 * The formula is the same one Explore optionchain uses — do not invent a
 * second illustrative premium.
 */

import { describe, expect, it } from "vitest";

import { sampleChainOptionLtp } from "../sampleOptionChain";

describe("sampleChainOptionLtp", () => {
  it("seeds a non-zero ATM CE premium from the Explore sample-chain formula", () => {
    // Options Builder NIFTY seed: ATM 22500, gap 50.
    expect(sampleChainOptionLtp(22500, 22500, 50, "CE")).toBe(45);
    expect(sampleChainOptionLtp(22500, 22500, 50, "PE")).toBe(45);
  });

  it("adds intrinsic value away from ATM the same way makeMockOptionChain does", () => {
    // One gap above ATM: CE is OTM (time value only), PE is ITM (+50 intrinsic).
    expect(sampleChainOptionLtp(22500, 22550, 50, "CE")).toBe(36.84);
    expect(sampleChainOptionLtp(22500, 22550, 50, "PE")).toBe(86.84);
  });
});
