/**
 * LeverageSection — Settings `#leverage` pane.
 *
 * Always shows real broker snapshot tiles or the honest empty
 * `Leverage settings unavailable.` plus Retry. Never returns null —
 * the Leverage tab stays in the nav, so a null render is a blank pane.
 */

import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Scale } from "lucide-react";
import { SectionTitle } from "./shared";
import { Button } from "@/components/ui/button";
import { getLeverageSettings } from "@/services/api";
import { useBrokerCapabilities } from "@/hooks/useBrokerCapabilities";
import type { LeverageSettings } from "@/types/api";

function LeverageTile({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="flex flex-col gap-0.5 p-3 rounded bg-surface-card border border-border-default">
      <span className="text-xxs text-text-muted uppercase tracking-wider">{label}</span>
      <span className="font-mono tabular-nums font-bold text-lg leading-tight text-text-primary">
        {value}
      </span>
    </div>
  );
}

function hasLeverageSnapshot(data: LeverageSettings | undefined): data is LeverageSettings {
  if (!data) return false;
  return (
    typeof data.available === "number"
    || typeof data.used === "number"
    || typeof data.total === "number"
    || typeof data.leverage_ratio === "number"
    || typeof data.leverage === "number"
    || typeof data.max_leverage === "number"
    || (typeof data.margin_mode === "string" && data.margin_mode.length > 0)
  );
}

function LeverageLoading({ copy }: { copy: string }) {
  return (
    <div className="space-y-6">
      <SectionTitle>Leverage</SectionTitle>
      <div className="flex items-center gap-2 text-xs text-text-muted" role="status" aria-live="polite">
        <RefreshCw size={12} className="animate-spin" aria-hidden="true" />
        {copy}
      </div>
    </div>
  );
}

function LeverageUnavailable({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="space-y-6">
      <SectionTitle>Leverage</SectionTitle>
      <div
        className="space-y-3 rounded-md border border-border-default bg-surface-hover/40 p-4"
        role="status"
        aria-live="polite"
      >
        <p className="text-sm font-medium text-text-primary">
          Leverage settings unavailable.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRetry}
          aria-label="Retry"
        >
          <RefreshCw size={12} aria-hidden="true" />
          Retry
        </Button>
      </div>
    </div>
  );
}

export function LeverageSection() {
  const capsQuery = useBrokerCapabilities();
  const supportsLeverage = capsQuery.data?.features?.leverage === true;

  const leverageQuery = useQuery<LeverageSettings>({
    queryKey: ["broker", "leverage"],
    queryFn: getLeverageSettings,
    enabled: supportsLeverage,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const handleRetry = () => {
    void capsQuery.refetch();
    if (supportsLeverage) {
      void leverageQuery.refetch();
    }
  };

  if (capsQuery.isLoading) {
    return <LeverageLoading copy="Checking broker capabilities..." />;
  }

  if (capsQuery.isError || !supportsLeverage) {
    return <LeverageUnavailable onRetry={handleRetry} />;
  }

  if (leverageQuery.isLoading) {
    return <LeverageLoading copy="Loading leverage settings..." />;
  }

  if (leverageQuery.isError || !hasLeverageSnapshot(leverageQuery.data)) {
    return <LeverageUnavailable onRetry={handleRetry} />;
  }

  const data = leverageQuery.data;
  const hasMarginSnapshot =
    typeof data.available === "number"
    || typeof data.used === "number"
    || typeof data.total === "number"
    || typeof data.leverage_ratio === "number";
  const usedPct =
    typeof data.leverage_ratio === "number"
      ? `${Math.round(data.leverage_ratio * 1000) / 10}%`
      : "—";

  return (
    <div className="space-y-6">
      <SectionTitle>Leverage</SectionTitle>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {hasMarginSnapshot ? (
          <>
            <LeverageTile label="Available Margin" value={data.available ?? "—"} />
            <LeverageTile label="Used Margin" value={data.used ?? "—"} />
            <LeverageTile label="Utilisation" value={usedPct} />
          </>
        ) : (
          <>
            <LeverageTile label="Current Leverage" value={`${data.leverage ?? "—"}x`} />
            <LeverageTile label="Max Leverage" value={`${data.max_leverage ?? "—"}x`} />
            <LeverageTile label="Margin Mode" value={data.margin_mode ?? "—"} />
          </>
        )}
      </div>

      <div className="flex items-start gap-2 p-3 rounded bg-surface-card border border-border-default text-xs text-text-muted">
        <Scale size={12} className="shrink-0 mt-0.5 text-accent" aria-hidden="true" />
        <span>
          Leverage settings are managed by your broker. Changes must be made
          in your broker&apos;s platform directly. This display reflects your
          current configuration.
        </span>
      </div>
    </div>
  );
}
