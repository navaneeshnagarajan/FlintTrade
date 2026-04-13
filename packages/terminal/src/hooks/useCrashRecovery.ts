/**
 * useCrashRecovery — detect whether the previous session ended unexpectedly.
 *
 * Mechanism:
 *   - On mount:  reads `flinttrade:session_active` from localStorage.
 *     If the flag is already `"true"`, the previous session did not clean up
 *     → expose `didCrash: true` and optionally fetch open position count.
 *   - Then immediately writes `"true"` to mark the current session as active.
 *   - On unmount: writes `"false"` to signal a clean exit.
 *
 * The hook is intentionally side-effect-only on mount/unmount.  Components
 * can read `didCrash` and `positionCount` to render a recovery banner.
 *
 * Usage::
 *
 *   const { didCrash, positionCount, dismiss } = useCrashRecovery();
 *
 *   if (didCrash) {
 *     return <CrashRecoveryBanner positionCount={positionCount} onDismiss={dismiss} />;
 *   }
 */

import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPositionbook } from "@/services/api";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { queryKeys } from "@/services/queryKeys";

const SESSION_FLAG_KEY = "flinttrade:session_active";

export interface CrashRecoveryState {
  /** True when the previous session did not call clean-up (likely crashed). */
  didCrash: boolean;
  /**
   * Number of open positions at the time of the check.
   * `null` while loading or when the broker is not connected.
   */
  positionCount: number | null;
  /** Call to manually dismiss the recovery banner. */
  dismiss: () => void;
}

export function useCrashRecovery(): CrashRecoveryState {
  // Did the previous session leave the flag set?
  const [didCrash, setDidCrash] = useState<boolean>(false);
  const [dismissed, setDismissed] = useState<boolean>(false);

  const isConnected = useBrokerConnected();

  // Fetch positions only when a crash was detected and broker is connected.
  const shouldFetchPositions = didCrash && !dismissed && isConnected;

  const positionsQuery = useQuery({
    queryKey: queryKeys.positions.all,
    queryFn: getPositionbook,
    enabled: shouldFetchPositions,
    // Single fetch is sufficient — no polling needed for this diagnostic
    staleTime: Infinity,
    retry: 1,
  });

  // On mount: check flag, set flag for current session
  useEffect(() => {
    try {
      const flagValue = localStorage.getItem(SESSION_FLAG_KEY);
      if (flagValue === "true") {
        setDidCrash(true);
      }
      // Mark current session as active
      localStorage.setItem(SESSION_FLAG_KEY, "true");
    } catch {
      // localStorage may be unavailable (private browsing, storage quota)
      // Silently ignore — crash detection is best-effort
    }

    // On unmount: mark clean exit
    return () => {
      try {
        localStorage.setItem(SESSION_FLAG_KEY, "false");
      } catch {
        // Ignore
      }
    };
  }, []);

  const dismiss = useCallback(() => {
    setDismissed(true);
    setDidCrash(false);
  }, []);

  const positions = positionsQuery.data ?? null;
  const positionCount =
    positions !== null ? positions.filter((p) => p.quantity !== 0).length : null;

  return {
    didCrash: didCrash && !dismissed,
    positionCount,
    dismiss,
  };
}
