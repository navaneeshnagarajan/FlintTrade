/**
 * Sticky operator status strip. primaryBanner kinds feed this strip;
 * there is no second banner.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import type { OperatorIncident } from "@/lib/operatorIncident";
import { primaryBannerCopy, type PrimaryBannerKind } from "@/lib/primaryBanner";
import { BROKER_ACCOUNTS_QUERY_KEY } from "@/hooks/useBrokerAccounts";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";

type StripLevel = "info" | "degraded" | "blocked";

function stripLevel(kind: Exclude<PrimaryBannerKind, null>, incident: OperatorIncident | null): StripLevel {
  if (incident && kind === incident.failureClass) return incident.level;
  if (kind === "live_risk") return "blocked";
  if (kind === "feed_disconnected") return "degraded";
  return "info";
}

const LEVEL_LABEL: Record<StripLevel, string> = {
  info: "Info",
  degraded: "Degraded",
  blocked: "Blocked",
};

export function OperatorStatusStrip({
  kind,
  incident,
}: {
  kind: Exclude<PrimaryBannerKind, null>;
  incident: OperatorIncident | null;
}) {
  const queryClient = useQueryClient();
  const [retrying, setRetrying] = useState(false);
  const showingIncident = incident !== null && kind === incident.failureClass;
  const level = stripLevel(kind, incident);
  const headline = showingIncident ? incident.headline : primaryBannerCopy(kind);
  const rectify = showingIncident ? incident.rectify : null;
  const showRetry = showingIncident && incident.failureClass !== "llm";

  async function retryOnce() {
    if (retrying) return;
    setRetrying(true);
    try {
      if (incident?.muteBrokerSmoke) {
        await queryClient.refetchQueries({ queryKey: BROKER_ACCOUNTS_QUERY_KEY });
        const state = queryClient.getQueryState(BROKER_ACCOUNTS_QUERY_KEY);
        if (state?.status === "success") {
          useOperatorSignalStore.getState().clearBrokerRateLimit();
        }
      }
      await queryClient.refetchQueries({ queryKey: ["operator", "ping"] });
      await queryClient.refetchQueries({ queryKey: ["operator", "health"] });
      await queryClient.refetchQueries({ queryKey: ["operator", "edge"] });
    } finally {
      setRetrying(false);
    }
  }

  if (!headline) return null;

  const tone = level === "blocked"
    ? "bg-loss/10 border-loss/20 text-loss"
    : level === "degraded"
      ? "bg-amber-500/10 border-amber-500/20 text-amber-400"
      : kind === "practice_sample"
        ? "bg-amber-500/10 border-amber-500/20 text-amber-400"
        : "bg-text-muted/10 border-text-muted/20 text-text-muted";

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="incident-strip"
      data-operator-strip="true"
      data-banner-kind={kind}
      data-strip-level={level}
      data-failure-class={showingIncident ? incident.failureClass : undefined}
      className={`sticky top-0 z-30 border-b px-4 py-1 ${tone}`}
    >
      <div className="flex items-center justify-center gap-2 text-center">
        <span className="text-xxs font-semibold uppercase tracking-wide">{LEVEL_LABEL[level]}</span>
        <p className="text-xs">{headline}</p>
        {showRetry ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-6 px-2 text-xxs"
            disabled={retrying}
            onClick={() => void retryOnce()}
          >
            {retrying ? "Retrying…" : "Retry once"}
          </Button>
        ) : null}
      </div>
      {rectify ? (
        <p className="text-xxs text-center" data-testid="operator-rectify">{rectify}</p>
      ) : null}
    </div>
  );
}
