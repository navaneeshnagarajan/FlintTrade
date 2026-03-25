import { describe, it, expect, beforeEach } from "vitest";
import { useSettingsStore } from "../settingsStore";

describe("settingsStore", () => {
  beforeEach(() => {
    useSettingsStore.setState(useSettingsStore.getInitialState());
  });

  // ---------------------------------------------------------------------------
  // Existing tests
  // ---------------------------------------------------------------------------

  it("initializes with trader persona", () => {
    expect(useSettingsStore.getState().persona).toBe("trader");
  });

  it("initializes with compact density", () => {
    expect(useSettingsStore.getState().density).toBe("compact");
  });

  it("updates persona", () => {
    useSettingsStore.getState().setPersona("investor");
    expect(useSettingsStore.getState().persona).toBe("investor");
  });

  it("updates trading defaults", () => {
    useSettingsStore.getState().setTradingDefaults({
      defaultExchange: "BSE",
      defaultProduct: "CNC",
      defaultQty: 10,
    });
    const state = useSettingsStore.getState();
    expect(state.defaultExchange).toBe("BSE");
    expect(state.defaultProduct).toBe("CNC");
    expect(state.defaultQty).toBe(10);
  });

  it("updates risk limits", () => {
    useSettingsStore.getState().setRiskLimits({ mtmStoploss: 10000 });
    expect(useSettingsStore.getState().riskLimits.mtmStoploss).toBe(10000);
  });

  // ---------------------------------------------------------------------------
  // v4 new fields — defaults
  // ---------------------------------------------------------------------------

  it("initializes with normal fontSize default", () => {
    expect(useSettingsStore.getState().fontSize).toBe("normal");
  });

  it("initializes with MARKET defaultOrderType", () => {
    expect(useSettingsStore.getState().defaultOrderType).toBe("MARKET");
  });

  it("initializes telegram with disabled and empty fields", () => {
    const { telegram } = useSettingsStore.getState();
    expect(telegram.enabled).toBe(false);
    expect(telegram.botToken).toBe("");
    expect(telegram.chatId).toBe("");
  });

  it("initializes dataPaths with empty strings", () => {
    const { dataPaths } = useSettingsStore.getState();
    expect(dataPaths.fastStoragePath).toBe("");
    expect(dataPaths.archiveStoragePath).toBe("");
  });

  it("initializes llm with host and apiKey fields", () => {
    const { llm } = useSettingsStore.getState();
    expect(llm).toHaveProperty("host");
    expect(llm).toHaveProperty("apiKey");
    expect(llm.host).toBe("");
    expect(llm.apiKey).toBe("");
  });

  // ---------------------------------------------------------------------------
  // theme field MUST NOT exist in v4
  // ---------------------------------------------------------------------------

  it("does not have a theme field (theme moved to themeStore)", () => {
    const state = useSettingsStore.getState() as unknown as Record<string, unknown>;
    expect(state).not.toHaveProperty("theme");
  });

  it("does not have a setTheme action (removed in v4)", () => {
    const state = useSettingsStore.getState() as unknown as Record<string, unknown>;
    expect(state).not.toHaveProperty("setTheme");
  });

  // ---------------------------------------------------------------------------
  // maxOrdersPerMinute (renamed from maxOrdersPerMin)
  // ---------------------------------------------------------------------------

  it("riskLimits uses maxOrdersPerMinute (not maxOrdersPerMin)", () => {
    const { riskLimits } = useSettingsStore.getState();
    expect(riskLimits).toHaveProperty("maxOrdersPerMinute");
    expect(riskLimits).not.toHaveProperty("maxOrdersPerMin");
  });

  it("updates maxOrdersPerMinute via setRiskLimits", () => {
    useSettingsStore.getState().setRiskLimits({ maxOrdersPerMinute: 60 });
    expect(useSettingsStore.getState().riskLimits.maxOrdersPerMinute).toBe(60);
  });

  // ---------------------------------------------------------------------------
  // Actions for new fields
  // ---------------------------------------------------------------------------

  it("setFontSize updates fontSize", () => {
    useSettingsStore.getState().setFontSize("large");
    expect(useSettingsStore.getState().fontSize).toBe("large");
  });

  it("setTelegram merges partial telegram settings", () => {
    useSettingsStore.getState().setTelegram({ enabled: true, botToken: "abc:def" });
    const { telegram } = useSettingsStore.getState();
    expect(telegram.enabled).toBe(true);
    expect(telegram.botToken).toBe("abc:def");
    expect(telegram.chatId).toBe(""); // unchanged
  });

  it("setDataPaths merges partial data paths", () => {
    useSettingsStore.getState().setDataPaths({ fastStoragePath: "/mnt/ssd/flinttrade" });
    const { dataPaths } = useSettingsStore.getState();
    expect(dataPaths.fastStoragePath).toBe("/mnt/ssd/flinttrade");
    expect(dataPaths.archiveStoragePath).toBe(""); // unchanged
  });

  // ---------------------------------------------------------------------------
  // v3 → v4 migration: maxOrdersPerMin rename
  // ---------------------------------------------------------------------------

  it("migration: transfers maxOrdersPerMin value to maxOrdersPerMinute", () => {
    // Simulate a v3 persisted state being migrated
    const store = useSettingsStore as unknown as {
      persist: { getOptions: () => { migrate?: (s: unknown, v: number) => unknown } };
    };
    const migrate = store.persist.getOptions().migrate;
    if (!migrate) throw new Error("migrate not configured");

    const v3State = {
      persona: "trader",
      density: "compact",
      riskLimits: {
        maxPositionLots: 5,
        mtmStoploss: 3000,
        mtmTarget: 8000,
        maxOrdersPerMin: 45,
      },
      llm: { provider: "openai", model: "gpt-4o", host: "", apiKey: "sk-test" },
    };

    const migrated = migrate(v3State, 3) as Record<string, unknown>;
    const risk = migrated.riskLimits as Record<string, unknown>;
    expect(risk.maxOrdersPerMinute).toBe(45);
    expect(risk).not.toHaveProperty("maxOrdersPerMin");
  });

  // ---------------------------------------------------------------------------
  // v3 → v4 migration: google → gemini
  // ---------------------------------------------------------------------------

  it("migration: fixes llm.provider 'google' to 'gemini'", () => {
    const store = useSettingsStore as unknown as {
      persist: { getOptions: () => { migrate?: (s: unknown, v: number) => unknown } };
    };
    const migrate = store.persist.getOptions().migrate;
    if (!migrate) throw new Error("migrate not configured");

    const v3State = {
      persona: "trader",
      density: "compact",
      riskLimits: { maxPositionLots: 10, mtmStoploss: 5000, mtmTarget: 10000, maxOrdersPerMin: 30 },
      llm: { provider: "google", model: "gemini-pro", host: "", apiKey: "goog-key" },
    };

    const migrated = migrate(v3State, 3) as Record<string, unknown>;
    const llm = migrated.llm as Record<string, unknown>;
    expect(llm.provider).toBe("gemini");
  });

  // ---------------------------------------------------------------------------
  // v3 → v4 migration: theme field removed
  // ---------------------------------------------------------------------------

  it("migration: removes theme field from persisted state", () => {
    const store = useSettingsStore as unknown as {
      persist: { getOptions: () => { migrate?: (s: unknown, v: number) => unknown } };
    };
    const migrate = store.persist.getOptions().migrate;
    if (!migrate) throw new Error("migrate not configured");

    const v3State = {
      persona: "trader",
      density: "compact",
      theme: "midnight",
      riskLimits: { maxPositionLots: 10, mtmStoploss: 5000, mtmTarget: 10000, maxOrdersPerMin: 30 },
      llm: { provider: "lmstudio", model: "", host: "", apiKey: "" },
    };

    const migrated = migrate(v3State, 3) as Record<string, unknown>;
    expect(migrated).not.toHaveProperty("theme");
  });

  // ---------------------------------------------------------------------------
  // Cascade migration: v1 → v4 in a single migrate() call
  // ---------------------------------------------------------------------------

  it("migration: v1 state cascades through all steps to reach v4", () => {
    // Zustand calls migrate() once with the stored version.
    // A v1 user must end up with all v2, v3, and v4 changes applied.
    const store = useSettingsStore as unknown as {
      persist: { getOptions: () => { migrate?: (s: unknown, v: number) => unknown } };
    };
    const migrate = store.persist.getOptions().migrate;
    if (!migrate) throw new Error("migrate not configured");

    const v1State = {
      persona: "trader",
      density: "compact",
      // v1 has no name/interests/experience/lastOpenTimestamp (added in v2)
      // v1 may have old "dark" theme (normalised in v3)
      theme: "dark",
      riskLimits: { maxPositionLots: 5, mtmStoploss: 2000, mtmTarget: 6000, maxOrdersPerMin: 20 },
      llm: { provider: "google", model: "gemini-pro" },
    };

    const migrated = migrate(v1State, 1) as Record<string, unknown>;

    // v2 step: profile fields added
    expect(migrated.name).toBe("Trader");
    expect(migrated.interests).toEqual([]);
    expect(migrated.experience).toBe("intermediate");

    // v4 step: theme removed (v3 normalised it to "midnight", v4 deletes it)
    expect(migrated).not.toHaveProperty("theme");

    // v4 step: maxOrdersPerMin renamed
    const risk = migrated.riskLimits as Record<string, unknown>;
    expect(risk.maxOrdersPerMinute).toBe(20);
    expect(risk).not.toHaveProperty("maxOrdersPerMin");

    // v4 step: google → gemini
    const llm = migrated.llm as Record<string, unknown>;
    expect(llm.provider).toBe("gemini");

    // v4 step: new fields present with defaults
    expect(migrated).toHaveProperty("telegram");
    expect(migrated).toHaveProperty("dataPaths");
    expect(migrated).toHaveProperty("fontSize");
    expect(migrated).toHaveProperty("defaultOrderType");
  });
});
