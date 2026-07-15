import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useModeStore, type AppMode } from "@/stores/modeStore";

/** Resolve whether account-backed reads have a valid source in the current mode. */
export function resolveAccountReadsEnabled(mode: AppMode, brokerConnected: boolean): boolean {
  return mode === "practice" || (mode === "live" && brokerConnected);
}

/**
 * Account data comes from the local sandbox in Practice and a connected broker
 * in Live. Explore owns its separate, labelled sample feed.
 */
export function useAccountReadsEnabled(): boolean {
  const mode = useModeStore((state) => state.mode);
  const brokerConnected = useBrokerConnected();
  return resolveAccountReadsEnabled(mode, brokerConnected);
}
