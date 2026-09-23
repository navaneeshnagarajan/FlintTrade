import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useModeStore } from "@/stores/modeStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useTradingStore } from "@/stores/tradingStore";

const mockBrokerConnected = vi.hoisted(() => ({ value: true }));
const mockSafety = vi.hoisted(() => ({
  kill_switch_active: false,
  daily_loss_hard_stop_active: false,
  daily_loss_pause_active: false,
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => mockBrokerConnected.value,
}));

vi.mock("@/services/ftApi", () => ({
  getSafetyConfig: () => Promise.resolve(mockSafety),
}));

import { usePrimaryBannerKind } from "../usePrimaryBannerKind";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("usePrimaryBannerKind", () => {
  beforeEach(() => {
    mockBrokerConnected.value = true;
    mockSafety.kill_switch_active = false;
    mockSafety.daily_loss_hard_stop_active = false;
    mockSafety.daily_loss_pause_active = false;
    useModeStore.setState({ mode: "live" });
    useOperatorSignalStore.setState({ decisionStatus: "ready" });
    useSettingsStore.setState({
      riskLimits: { ...useSettingsStore.getState().riskLimits, mtmStoploss: 0 },
    });
    useTradingStore.setState({ totalPnl: 0 });
  });

  it("Explore leaves the incident slot empty even when the feed is down", () => {
    useModeStore.setState({ mode: "explore" });
    mockBrokerConnected.value = false;
    const { result } = renderHook(() => usePrimaryBannerKind(), { wrapper });
    expect(result.current).toBeNull();
  });

  it("Live feed disconnect is the primary when Laya is Ready and there is no risk alert", () => {
    mockBrokerConnected.value = false;
    const { result } = renderHook(() => usePrimaryBannerKind(), { wrapper });
    expect(result.current).toBe("feed_disconnected");
  });

  it("Laya Down outranks a disconnected feed", () => {
    mockBrokerConnected.value = false;
    useOperatorSignalStore.setState({ decisionStatus: "down" });
    const { result } = renderHook(() => usePrimaryBannerKind(), { wrapper });
    expect(result.current).toBe("laya");
  });

  it("client daily-loss alert is Live risk even if the feed is down", () => {
    mockBrokerConnected.value = false;
    useSettingsStore.setState({
      riskLimits: { ...useSettingsStore.getState().riskLimits, mtmStoploss: 5000 },
    });
    useTradingStore.setState({ totalPnl: -2500 });
    const { result } = renderHook(() => usePrimaryBannerKind(), { wrapper });
    expect(result.current).toBe("live_risk");
  });
});
