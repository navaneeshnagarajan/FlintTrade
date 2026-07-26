/**
 * optionLegSymbols.test.ts
 *
 * The API layer is mocked; the compact-symbol builder and future-expiry
 * selection run for real. Expiry fixtures sit in 2099 so nearest-future
 * selection stays deterministic without faking time.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
  getOptionSymbol: vi.fn(),
}));

vi.mock("@/services/api", () => ({
  getExpiry: apiMocks.getExpiry,
  getOptionChain: apiMocks.getOptionChain,
  getOptionSymbol: apiMocks.getOptionSymbol,
}));

import { resolveOptionLeg } from "@/lib/optionLegSymbols";

describe("resolveOptionLeg", () => {
  beforeEach(() => {
    apiMocks.getExpiry.mockReset();
    apiMocks.getOptionChain.mockReset();
    apiMocks.getOptionSymbol.mockReset();
  });

  it("resolves an explicit expiry and strike through the broker resolver", async () => {
    apiMocks.getOptionSymbol.mockResolvedValue({ symbol: "NIFTY25JUN9924800CE", exchange: "NFO" });

    const leg = await resolveOptionLeg({
      underlying: "NIFTY",
      leg: "CE",
      expiry: "25-JUN-99",
      strike: "24800",
    });

    expect(apiMocks.getOptionSymbol).toHaveBeenCalledWith("NIFTY", "NFO", "25-JUN-99", "CE", "24800");
    expect(apiMocks.getExpiry).not.toHaveBeenCalled();
    expect(apiMocks.getOptionChain).not.toHaveBeenCalled();
    expect(leg).toEqual({
      symbol: "NIFTY25JUN9924800CE",
      exchange: "NFO",
      strike: "24800",
      expiry: "25-JUN-99",
    });
  });

  it("picks the nearest future expiry when none is given", async () => {
    // Deliberately unsorted, with a long-past entry first — ThreePanel's
    // list[0] would have loaded the 2020 contract.
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["01-JAN-20", "30-DEC-99", "25-JUN-99"] });
    apiMocks.getOptionSymbol.mockResolvedValue({ symbol: "NIFTY25JUN9924800PE", exchange: "NFO" });

    const leg = await resolveOptionLeg({ underlying: "NIFTY", leg: "PE", strike: "24800" });

    expect(apiMocks.getExpiry).toHaveBeenCalledWith("NIFTY", "NFO", "options");
    expect(apiMocks.getOptionSymbol).toHaveBeenCalledWith("NIFTY", "NFO", "25-JUN-99", "PE", "24800");
    expect(leg.expiry).toBe("25-JUN-99");
  });

  it("fills in the ATM strike from the option chain when none is given", async () => {
    apiMocks.getOptionChain.mockResolvedValue({ atm_strike: 24850 });
    apiMocks.getOptionSymbol.mockResolvedValue({ symbol: "NIFTY25JUN9924850CE", exchange: "NFO" });

    const leg = await resolveOptionLeg({ underlying: "NIFTY", leg: "CE", expiry: "25-JUN-99" });

    expect(apiMocks.getOptionChain).toHaveBeenCalledWith("NIFTY", "NFO", "25-JUN-99");
    expect(apiMocks.getOptionSymbol).toHaveBeenCalledWith("NIFTY", "NFO", "25-JUN-99", "CE", "24850");
    expect(leg.strike).toBe("24850");
  });

  it('treats strike "0" as the ATM sentinel, as ThreePanel did', async () => {
    apiMocks.getOptionChain.mockResolvedValue({ atm_strike: 51200 });
    apiMocks.getOptionSymbol.mockResolvedValue({ symbol: "BANKNIFTY25JUN9951200PE", exchange: "NFO" });

    const leg = await resolveOptionLeg({
      underlying: "BANKNIFTY",
      leg: "PE",
      expiry: "25-JUN-99",
      strike: "0",
    });

    expect(apiMocks.getOptionChain).toHaveBeenCalledWith("BANKNIFTY", "NFO", "25-JUN-99");
    expect(leg.strike).toBe("51200");
  });

  it("falls back to the compact symbol when the broker resolver fails", async () => {
    apiMocks.getOptionSymbol.mockRejectedValue(new Error("resolver down"));

    const leg = await resolveOptionLeg({
      underlying: "NIFTY",
      leg: "CE",
      expiry: "25-JUN-99",
      strike: "24800",
    });

    expect(leg).toEqual({
      symbol: "NIFTY25JUN9924800CE",
      exchange: "NFO",
      strike: "24800",
      expiry: "25-JUN-99",
    });
  });

  it("falls back to the compact symbol when the resolver returns nothing usable", async () => {
    apiMocks.getOptionSymbol.mockResolvedValue({ symbol: "", exchange: "NFO" });

    const leg = await resolveOptionLeg({
      underlying: "NIFTY",
      leg: "PE",
      expiry: "25-JUN-99",
      strike: "24800",
    });

    expect(leg.symbol).toBe("NIFTY25JUN9924800PE");
  });

  it("resolves ATM end to end with the compact fallback (the full ThreePanel path)", async () => {
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["25-JUN-99"] });
    apiMocks.getOptionChain.mockResolvedValue({ atm_strike: 24800 });
    apiMocks.getOptionSymbol.mockRejectedValue(new Error("resolver down"));

    const leg = await resolveOptionLeg({ underlying: "nifty", leg: "CE" });

    expect(leg).toEqual({
      symbol: "NIFTY25JUN9924800CE",
      exchange: "NFO",
      strike: "24800",
      expiry: "25-JUN-99",
    });
  });

  it("throws when the expiry list is empty", async () => {
    apiMocks.getExpiry.mockResolvedValue({ expiry: [] });

    await expect(resolveOptionLeg({ underlying: "NIFTY", leg: "CE" }))
      .rejects.toThrow("No option expiries available for NIFTY");
  });

  it("throws when the expiry list cannot be loaded", async () => {
    apiMocks.getExpiry.mockRejectedValue(new Error("network"));

    await expect(resolveOptionLeg({ underlying: "NIFTY", leg: "CE" }))
      .rejects.toThrow("Could not load option expiries for NIFTY");
  });

  it("throws when the option chain carries no ATM strike", async () => {
    apiMocks.getOptionChain.mockResolvedValue({ strikes: [] });

    await expect(resolveOptionLeg({ underlying: "NIFTY", leg: "CE", expiry: "25-JUN-99" }))
      .rejects.toThrow("Option chain for NIFTY 25-JUN-99 carries no ATM strike");
  });

  it("throws when the option chain cannot be loaded", async () => {
    apiMocks.getOptionChain.mockRejectedValue(new Error("network"));

    await expect(resolveOptionLeg({ underlying: "NIFTY", leg: "PE", expiry: "25-JUN-99" }))
      .rejects.toThrow("Could not load the option chain for NIFTY 25-JUN-99");
  });

  it("throws when the underlying is blank", async () => {
    await expect(resolveOptionLeg({ underlying: "   ", leg: "CE" }))
      .rejects.toThrow("An option leg needs an underlying symbol");
    expect(apiMocks.getExpiry).not.toHaveBeenCalled();
  });

  it("fills a missing resolver exchange with the requested option exchange", async () => {
    apiMocks.getOptionSymbol.mockResolvedValue({ symbol: "NIFTY25JUN9924800CE", exchange: "" });

    const leg = await resolveOptionLeg({
      underlying: "NIFTY",
      leg: "CE",
      expiry: "25-JUN-99",
      strike: "24800",
    });

    expect(leg.exchange).toBe("NFO");
  });
});
