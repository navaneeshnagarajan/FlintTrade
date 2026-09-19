/**
 * Live feed-freshness for TopBar, ticker, and Market Clock.
 *
 * Combines execution mode, WebSocket diagnostics, and the REST ticker
 * fallback health report. Recomputes once a second so Stale/Unknown age
 * stays visible.
 */

import { useEffect, useState } from "react";
import { useAtomValue } from "jotai";
import { tickerFallbackStatusAtom } from "@/hooks/useTickerFallback";
import { resolveFeedFreshness, type FeedFreshness } from "@/lib/feedFreshness";
import { getWsService } from "@/services/websocket";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";

function latestTickAt(fallbackLastUpdatedAt: number | null): number | null {
  const wsTs = getWsService()?.diagnostics.lastTickTimestamp ?? 0;
  const fallbackTs = fallbackLastUpdatedAt ?? 0;
  const best = Math.max(wsTs, fallbackTs);
  return best > 0 ? best : null;
}

export function useFeedFreshness(): FeedFreshness {
  const mode = useModeStore((s) => s.mode);
  const wsConnected = Boolean(useConnectionStore((s) => s.wsConnected));
  const fallback = useAtomValue(tickerFallbackStatusAtom);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, []);

  return resolveFeedFreshness({
    mode,
    wsConnected,
    fallbackActive: fallback.active,
    fallbackStale: fallback.isStale,
    lastTickAt: latestTickAt(fallback.lastUpdatedAt),
    now,
  });
}
