/**
 * useSettingsState tests
 *
 * Tests that the hook correctly reads from settingsStore + connectionStore
 * and exposes the right section data shapes.
 *
 * The websocket service is mocked so resetWsService doesn't blow up in jsdom.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useSettingsState } from "../useSettingsState";
import { useSettingsStore } from "@/stores/settingsStore";
import { useConnectionStore } from "@/stores/connectionStore";

// ---------------------------------------------------------------------------
// Mock the websocket service (resetWsService would fail in jsdom)
// ---------------------------------------------------------------------------

vi.mock("@/services/websocket", () => ({
  resetWsService: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resetStores() {
  useSettingsStore.setState(useSettingsStore.getInitialState());
  useConnectionStore.setState(useConnectionStore.getInitialState());
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useSettingsState", () => {
  beforeEach(() => {
    resetStores();
  });

  it("returns general with fontSize from settingsStore", () => {
    useSettingsStore.setState({ fontSize: "large" });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.general.fontSize).toBe("large");
  });

  it("returns trading defaults from settingsStore", () => {
    useSettingsStore.setState({
      defaultExchange: "BSE",
      defaultProduct: "CNC",
      defaultOrderType: "LIMIT",
      defaultQty: 5,
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.trading.exchange).toBe("BSE");
    expect(result.current.trading.product).toBe("CNC");
    expect(result.current.trading.orderType).toBe("LIMIT");
    expect(result.current.trading.quantity).toBe("5");
  });

  it("returns risk limits as string values for form inputs", () => {
    useSettingsStore.setState({
      riskLimits: {
        maxPositionLots: 10,
        mtmStoploss: 5000,
        mtmTarget: 10000,
        maxOrdersPerMinute: 30,
      },
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.risk.maxPositionLots).toBe("10");
    expect(result.current.risk.mtmStoploss).toBe("5000");
    expect(result.current.risk.mtmTarget).toBe("10000");
    expect(result.current.risk.maxOrdersPerMinute).toBe("30");
  });

  it("returns connection data from connectionStore", () => {
    useConnectionStore.setState({
      host: "http://192.168.1.10:5000",
      apiKey: "test-api-key",
      wsUrl: "ws://192.168.1.10:8765",
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.connection.host).toBe("http://192.168.1.10:5000");
    expect(result.current.connection.apiKey).toBe("test-api-key");
    expect(result.current.connection.wsPort).toBe("8765");
  });

  it("returns telegram settings from settingsStore", () => {
    useSettingsStore.setState({
      telegram: { enabled: true, botToken: "bot:token", chatId: "-100123" },
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.telegram.enabled).toBe(true);
    expect(result.current.telegram.botToken).toBe("bot:token");
    expect(result.current.telegram.chatId).toBe("-100123");
  });

  it("returns dataPaths from settingsStore", () => {
    useSettingsStore.setState({
      dataPaths: { fastStoragePath: "/ssd/data", archiveStoragePath: "/hdd/archive" },
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.dataPaths.fastStoragePath).toBe("/ssd/data");
    expect(result.current.dataPaths.archiveStoragePath).toBe("/hdd/archive");
  });

  it("returns llm data from settingsStore with lmstudio default provider", () => {
    // With empty provider, hook defaults to "lmstudio"
    useSettingsStore.setState({
      llm: { provider: "", model: "qwen3:9b", host: "http://127.0.0.1:1234", apiKey: "" },
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.llm.provider).toBe("lmstudio");
    expect(result.current.llm.model).toBe("qwen3:9b");
  });

  it("exposes update action functions", () => {
    const { result } = renderHook(() => useSettingsState());

    expect(typeof result.current.updateGeneral).toBe("function");
    expect(typeof result.current.updateTradingDefaults).toBe("function");
    expect(typeof result.current.updateRiskLimits).toBe("function");
    expect(typeof result.current.updateLLM).toBe("function");
    expect(typeof result.current.updateTelegram).toBe("function");
    expect(typeof result.current.updateDataPaths).toBe("function");
    expect(typeof result.current.updateConnection).toBe("function");
    expect(typeof result.current.handleRestart).toBe("function");
  });

  it("restarting is false by default", () => {
    const { result } = renderHook(() => useSettingsState());
    expect(result.current.restarting).toBe(false);
  });

  it("preserves zero risk values as '0' (not empty string)", () => {
    // 0 is a valid limit value — the hook must not coerce it to "" via falsy check.
    useSettingsStore.setState({
      riskLimits: {
        maxPositionLots: 0,
        mtmStoploss: 0,
        mtmTarget: 0,
        maxOrdersPerMinute: 0,
      },
    });

    const { result } = renderHook(() => useSettingsState());

    expect(result.current.risk.maxPositionLots).toBe("0");
    expect(result.current.risk.mtmStoploss).toBe("0");
    expect(result.current.risk.mtmTarget).toBe("0");
    expect(result.current.risk.maxOrdersPerMinute).toBe("0");
  });
});
