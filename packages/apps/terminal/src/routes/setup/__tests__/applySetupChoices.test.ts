import { beforeEach, describe, expect, it, vi } from "vitest";

const storeMocks = vi.hoisted(() => ({
  setConfig: vi.fn(),
  setPersona: vi.fn(),
  setName: vi.fn(),
  setInterests: vi.fn(),
  setExperience: vi.fn(),
  setTradingDefaults: vi.fn(),
  setRiskLimits: vi.fn(),
  setGlobalLevel: vi.fn(),
  setRouteOverride: vi.fn(),
  applyPreset: vi.fn(),
  saveTabLayout: vi.fn(),
}));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: {
    getState: () => ({ setConfig: storeMocks.setConfig }),
  },
}));

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: {
    getState: () => ({
      setPersona: storeMocks.setPersona,
      setName: storeMocks.setName,
      setInterests: storeMocks.setInterests,
      setExperience: storeMocks.setExperience,
      setTradingDefaults: storeMocks.setTradingDefaults,
      setRiskLimits: storeMocks.setRiskLimits,
    }),
  },
}));

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: {
    getState: () => ({
      setGlobalLevel: storeMocks.setGlobalLevel,
      setRouteOverride: storeMocks.setRouteOverride,
    }),
  },
}));

vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: {
    getState: () => ({
      dockviewApi: null,
      activeTabId: "trade",
      applyPreset: storeMocks.applyPreset,
      saveTabLayout: storeMocks.saveTabLayout,
    }),
  },
}));

import { persistSetupChoices } from "../applySetupChoices";

describe("persistSetupChoices", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
  });

  it("persists OpenAlgo bridge, profile, skill, trading, risk, and pending layout choices", () => {
    const destination = persistSetupChoices({
      persona: "investor",
      experience: "professional",
      connection: {
        host: "http://localhost:5000",
        apiKey: "test-api-key",
        wsPort: "8765",
      },
      tradingDefaults: {
        defaultExchange: "NSE",
        defaultProduct: "CNC",
        defaultQty: 5,
      },
      riskLimits: {
        maxPositionLots: 3,
        mtmStoploss: 2500,
        mtmTarget: 5000,
        maxOrdersPerMinute: 12,
      },
      name: "Nav",
      interests: ["investing"],
    });

    expect(destination).toBe("/invest");
    expect(storeMocks.setConfig).toHaveBeenCalledWith({
      host: "http://localhost:5000",
      apiKey: "test-api-key",
      wsUrl: "ws://localhost:8765",
    });
    expect(fetch).toHaveBeenCalledWith(
      "/ft-api/v1/config/openalgo",
      expect.objectContaining({ method: "POST" }),
    );
    expect(storeMocks.setPersona).toHaveBeenCalledWith("investor");
    expect(storeMocks.setName).toHaveBeenCalledWith("Nav");
    expect(storeMocks.setInterests).toHaveBeenCalledWith(["investing"]);
    expect(storeMocks.setExperience).toHaveBeenCalledWith("pro");
    expect(storeMocks.setGlobalLevel).toHaveBeenCalledWith("intermediate");
    expect(storeMocks.setRouteOverride).toHaveBeenCalledWith("invest", "advanced");
    expect(storeMocks.setTradingDefaults).toHaveBeenCalledWith({
      defaultExchange: "NSE",
      defaultProduct: "CNC",
      defaultQty: 5,
    });
    expect(storeMocks.setRiskLimits).toHaveBeenCalledWith({
      maxPositionLots: 3,
      mtmStoploss: 2500,
      mtmTarget: 5000,
      maxOrdersPerMinute: 12,
    });
    expect(storeMocks.saveTabLayout).toHaveBeenCalledWith(
      "trade",
      expect.objectContaining({ __pendingPreset: "scalper-zone" }),
    );
  });

  it("does not persist the Direct Connect placeholder as OpenAlgo configuration", () => {
    const destination = persistSetupChoices({
      persona: "trader",
      connection: {
        host: "http://127.0.0.1:5100",
        apiKey: "direct-connect",
        wsPort: "8765",
      },
    });

    expect(destination).toBe("/trade");
    expect(storeMocks.setConfig).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });
});
