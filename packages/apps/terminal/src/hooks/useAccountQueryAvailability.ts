import { useSyncExternalStore } from "react";
import { onlineManager } from "@tanstack/react-query";
import {
  resolveAccountQueryAvailability,
  type AccountQueryAvailabilityInput,
} from "@/lib/accountQueryState";

const subscribeOnline = (onChange: () => void) => onlineManager.subscribe(onChange);
const readOnline = () => onlineManager.isOnline();

/** React to offline-idle transitions even when the query itself is unchanged. */
export function useAccountQueryAvailability(input: Omit<AccountQueryAvailabilityInput, "isOnline">) {
  const isOnline = useSyncExternalStore(subscribeOnline, readOnline, readOnline);
  return resolveAccountQueryAvailability({ ...input, isOnline });
}
