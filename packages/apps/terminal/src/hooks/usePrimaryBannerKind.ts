/**
 * FT-UX-001 — single primary-banner kind for shared chrome.
 *
 * Explore / Practice always own the strip. Live risk beats a disconnected
 * feed so the desk never stacks two announcement banners.
 */

import { useQuery } from "@tanstack/react-query";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { selectPrimaryBanner, type PrimaryBannerKind } from "@/lib/primaryBanner";
import { getSafetyConfig } from "@/services/ftApi";
import { useModeStore } from "@/stores/modeStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useTradingStore } from "@/stores/tradingStore";

const SAFETY_CONFIG_QUERY_KEY = ["safetyConfig"] as const;

export function useLiveRiskActive(): boolean {
  const mode = useModeStore((s) => s.mode);
  const totalPnl = useTradingStore((s) => s.totalPnl);
  const mtmStoploss = useSettingsStore((s) => s.riskLimits.mtmStoploss);
  const { data } = useQuery({
    queryKey: SAFETY_CONFIG_QUERY_KEY,
    queryFn: getSafetyConfig,
    enabled: mode === "live",
    refetchInterval: 5_000,
  });

  if (mode !== "live") return false;

  const killActive = data?.kill_switch_active === true;
  const dailyLossHalt =
    data?.daily_loss_hard_stop_active === true || data?.daily_loss_pause_active === true;
  const dailyLossAlert =
    mtmStoploss > 0 && totalPnl < 0 && Math.abs(totalPnl) >= mtmStoploss * 0.5;
  return killActive || dailyLossHalt || dailyLossAlert;
}

export function usePrimaryBannerKind(): PrimaryBannerKind {
  const mode = useModeStore((s) => s.mode);
  const liveRiskActive = useLiveRiskActive();
  const feedDisconnected = !useBrokerConnected();
  return selectPrimaryBanner({ mode, liveRiskActive, feedDisconnected });
}
