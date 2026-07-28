import { beforeEach, describe, expect, it, vi } from "vitest";

const storeMocks = vi.hoisted(() => ({
  setPersona: vi.fn(),
  setName: vi.fn(),
  setInterests: vi.fn(),
  setExperience: vi.fn(),
  setTradingDefaults: vi.fn(),
  setRiskLimits: vi.fn(),
  setLLMSetupDraft: vi.fn(),
  setGlobalLevel: vi.fn(),
  setRouteOverride: vi.fn(),
  applyPreset: vi.fn(),
  saveTabLayout: vi.fn(),
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
      setLLMSetupDraft: storeMocks.setLLMSetupDraft,
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
      workspaceApi: null,
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

  it("persists profile, skill, trading, risk, LLM, and pending layout choices", () => {
    const destination = persistSetupChoices({
      persona: "investor",
      experience: "professional",
      connection: {
        host: "http://localhost:5000",
        port: "5000",
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
      llm: {
        provider: "grok",
        model: "grok-3-mini",
        host: "",
      },
      name: "Nav",
      interests: ["investing"],
    });

    expect(destination).toBe("/invest");
    // ConnectionStep has already committed the connection transaction before
    // this final profile/layout projection runs.
    expect(fetch).not.toHaveBeenCalled();
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
    expect(storeMocks.setLLMSetupDraft).toHaveBeenCalledWith({
      provider: "grok",
      authMode: "api-key",
      model: "grok-3-mini",
      host: "",
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
        port: "5100",
        apiKey: "direct-connect",
        wsPort: "8765",
      },
    });

    expect(destination).toBe("/trade");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("normalises a legacy managed Ollama host before storing the setup draft", () => {
    persistSetupChoices({
      persona: "trader",
      llm: {
        provider: "ollama",
        model: "qwen3:8b",
        host: "http://127.0.0.1:11434",
      },
    });

    expect(storeMocks.setLLMSetupDraft).toHaveBeenCalledWith({
      provider: "ollama",
      authMode: "api-key",
      model: "qwen3:8b",
      host: "",
    });
  });

  it("stores Claude Code OAuth as an Anthropic backend with a separate auth marker", () => {
    persistSetupChoices({
      persona: "trader",
      llm: {
        provider: "claude-code-oauth",
        model: "claude-3-5-haiku-20241022",
        host: "",
      },
    });

    expect(storeMocks.setLLMSetupDraft).toHaveBeenCalledWith({
      provider: "anthropic",
      authMode: "claude-code-oauth",
      model: "claude-3-5-haiku-20241022",
      host: "",
    });
  });
});
