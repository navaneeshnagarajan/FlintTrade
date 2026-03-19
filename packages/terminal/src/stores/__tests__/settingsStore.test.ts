import { describe, it, expect, beforeEach } from "vitest";
import { useSettingsStore } from "../settingsStore";

describe("settingsStore", () => {
  beforeEach(() => {
    useSettingsStore.setState(useSettingsStore.getInitialState());
  });

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
});
