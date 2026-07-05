/**
 * LeverageSection — displays current leverage settings for crypto brokers.
 *
 * Only visible when the connected broker supports leverage. Fetches
 * FlintTrade's backend margin/leverage snapshot.
 */

import { useQuery } from "@tanstack/react-query";
import { RefreshCw, AlertTriangle, Scale } from "lucide-react";
import { SectionTitle } from "./shared";
import { getLeverageSettings } from "@/services/api";
import { useBrokerCapabilities } from "@/hooks/useBrokerCapabilities";
import type { LeverageSettings } from "@/types/api";

// ---------------------------------------------------------------------------
// Stat tile
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function LeverageSection() {
  const { data: caps, isLoading: capsLoading } = useBrokerCapabilities();
  const supportsLeverage = caps?.features?.leverage === true;

  const leverageQuery = useQuery<LeverageSettings>({
    queryKey: ["broker", "leverage"],
    queryFn: getLeverageSettings,
    enabled: supportsLeverage,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  // Don't render the section at all if broker doesn't support leverage
  if (capsLoading) {
    return (
      <div className="space-y-6">
        <SectionTitle>Leverage</SectionTitle>
        <div className="flex items-center gap-2 text-xs text-text-muted">
          <RefreshCw size={12} className="animate-spin" />
          Checking broker capabilities...
        </div>
      </div>
    );
  }

  if (!supportsLeverage) {
    return null;
  }

  const data = leverageQuery.data;
  const hasMarginSnapshot =
    typeof data?.available === "number"
    || typeof data?.used === "number"
    || typeof data?.total === "number"
    || typeof data?.leverage_ratio === "number";
  const usedPct =
    typeof data?.leverage_ratio === "number"
      ? `${Math.round(data.leverage_ratio * 1000) / 10}%`
      : "—";

  return (
    <div className="space-y-6">
      <SectionTitle>Leverage</SectionTitle>

      {leverageQuery.isLoading && (
        <div className="flex items-center gap-2 text-xs text-text-muted">
          <RefreshCw size={12} className="animate-spin" />
          Loading leverage settings...
        </div>
      )}

      {leverageQuery.isError && (
        <div className="flex items-center gap-2 text-xs text-warning">
          <AlertTriangle size={12} />
          Failed to load leverage settings
        </div>
      )}

      {data && (
        <>
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

          {/* Info notice */}
          <div className="flex items-start gap-2 p-3 rounded bg-surface-card border border-border-default text-xs text-text-muted">
            <Scale size={12} className="shrink-0 mt-0.5 text-accent" />
            <span>
              Leverage settings are managed by your broker. Changes must be made
              in your broker&apos;s platform directly. This display reflects your
              current configuration.
            </span>
          </div>
        </>
      )}
    </div>
  );
}
