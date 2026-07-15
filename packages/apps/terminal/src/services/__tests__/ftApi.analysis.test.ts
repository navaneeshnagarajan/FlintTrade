import { beforeEach, describe, expect, it, vi } from "vitest";

const helperMocks = vi.hoisted(() => ({
  post: vi.fn(),
}));

vi.mock("../ftApi.helpers", () => ({
  get: vi.fn(),
  post: helperMocks.post,
  postV1: vi.fn(),
}));

import { getGammaDensityData } from "../ftApi.analysis";

function validGammaDensityPayload() {
  return {
    underlying: "NIFTY",
    exchange: "NFO",
    spot_price: 24000,
    atm_strike: 24000,
    atm_iv: 16.4,
    dte_days: 7,
    peak_intraday_strike: 24000,
    peak_expiry_strike: 24000,
    intraday_band: {
      sigma_move: 150,
      one_sigma_low: 23850,
      one_sigma_high: 24150,
      two_sigma_low: 23700,
      two_sigma_high: 24300,
    },
    expiry_band: {
      sigma_move: 300,
      one_sigma_low: 23700,
      one_sigma_high: 24300,
      two_sigma_low: 23400,
      two_sigma_high: 24600,
    },
    strikes: [{
      strike: 24000,
      ce_oi: 1000,
      pe_oi: 1200,
      iv: 16.4,
      density_intraday: 900,
      density_expiry: 600,
    }],
    is_sample_data: false,
  };
}

describe("Gamma Density API validation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns a fully validated payload with explicit provenance", async () => {
    const payload = validGammaDensityPayload();
    helperMocks.post.mockResolvedValue(payload);

    await expect(getGammaDensityData("NIFTY", "NFO", "2099-07-30")).resolves.toEqual(payload);
  });

  it.each([
    ["string DTE", (payload: ReturnType<typeof validGammaDensityPayload>) => {
      (payload as Record<string, unknown>).dte_days = "7";
    }],
    ["string density", (payload: ReturnType<typeof validGammaDensityPayload>) => {
      (payload.strikes[0] as Record<string, unknown>).density_intraday = "900";
    }],
  ])("rejects %s before chart arithmetic", async (_label, mutate) => {
    const payload = validGammaDensityPayload();
    mutate(payload);
    helperMocks.post.mockResolvedValue(payload);

    await expect(getGammaDensityData("NIFTY", "NFO", "2099-07-30"))
      .rejects.toThrow(/Invalid Gamma Density/i);
  });

  it.each([undefined, "false"])(
    "rejects missing or malformed provenance: %s",
    async (provenance) => {
      const payload = validGammaDensityPayload() as Record<string, unknown>;
      if (provenance === undefined) delete payload.is_sample_data;
      else payload.is_sample_data = provenance;
      helperMocks.post.mockResolvedValue(payload);

      await expect(getGammaDensityData("NIFTY", "NFO", "2099-07-30"))
        .rejects.toThrow(/provenance/i);
    },
  );
});
