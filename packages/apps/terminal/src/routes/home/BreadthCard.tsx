/**
 * BreadthCard — Advances/Declines/Unchanged with bar chart.
 *
 * Live when a broker is connected: fetches the real market-breadth snapshot
 * from /ft-api/v1/breadth/current (the same endpoint MarketBreadthWidget uses),
 * which reports `is_sample_data: false` when it served live registry data. When
 * disconnected — or the backend served its own sample fallback — it shows the
 * deterministic SAMPLE_BREADTH with a Demo badge, so the figures are never
 * mistaken for live NSE breadth.
 */

import { useQuery } from "@tanstack/react-query";
import { BentoCard } from "@/components/bento/BentoCard";
import { BarChart2 } from "lucide-react";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { DemoBadge } from "./DemoBadge";

interface Breadth {
  advances: number;
  declines: number;
  unchanged: number;
}

// Deterministic fallback shown when not connected / backend served sample.
const SAMPLE_BREADTH: Breadth = {
  advances: 1320,
  declines: 780,
  unchanged: 200,
};

interface BreadthResult {
  isSample: boolean;
  breadth: Breadth;
}

/** Fetch the live breadth snapshot; null on any failure (→ sample fallback). */
async function fetchBreadth(): Promise<BreadthResult | null> {
  const res = await fetch("/ft-api/v1/breadth/current");
  if (!res.ok) return null;
  const json: unknown = await res.json();
  const j = json as { status?: string; is_sample_data?: boolean; data?: Partial<Breadth> } | null;
  if (!j || j.status !== "success" || !j.data) return null;
  const { advances, declines, unchanged } = j.data;
  if (typeof advances !== "number" || typeof declines !== "number" || typeof unchanged !== "number") {
    return null;
  }
  return { isSample: j.is_sample_data !== false, breadth: { advances, declines, unchanged } };
}

export function BreadthCard() {
  const isConnected = useBrokerConnected();

  const { data: live } = useQuery({
    queryKey: ["home-breadth"],
    queryFn: fetchBreadth,
    enabled: isConnected,
    staleTime: 60_000,
    refetchInterval: isConnected ? 60_000 : false,
    retry: false,
  });

  // Live only when connected AND the backend served real (non-sample) data.
  const isLive = isConnected && live != null && live.isSample === false;
  const breadth = isLive && live ? live.breadth : SAMPLE_BREADTH;

  const total = breadth.advances + breadth.declines + breadth.unchanged;
  const advPct = total > 0 ? (breadth.advances / total) * 100 : 0;
  const decPct = total > 0 ? (breadth.declines / total) * 100 : 0;
  const unchPct = total > 0 ? (breadth.unchanged / total) * 100 : 0;

  return (
    <BentoCard
      size="default"
      label={isLive ? "Market Breadth" : "Market Breadth (placeholder data)"}
      data-testid="breadth-card"
    >
      {!isLive && (
        <DemoBadge testId="breadth-demo-badge" title="Placeholder breadth — not live NSE data" />
      )}
      <div className="p-4 h-full flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <BarChart2 size={13} className="text-text-muted" aria-hidden="true" />
          <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
            Market Breadth
          </p>
        </div>

        {/* Bar */}
        <div
          className="flex h-2 rounded-full overflow-hidden"
          role="img"
          aria-label={`Advances: ${breadth.advances}, Declines: ${breadth.declines}, Unchanged: ${breadth.unchanged}`}
        >
          <div style={{ width: `${advPct}%`, background: "var(--color-bullish-text)" }} />
          <div style={{ width: `${unchPct}%`, background: "var(--color-text-muted)" }} />
          <div style={{ width: `${decPct}%`, background: "var(--color-bearish-text)" }} />
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-2 text-center">
          <div>
            <p className="font-mono text-sm font-semibold text-bullish-text">
              {breadth.advances.toLocaleString()}
            </p>
            <p className="text-[10px] text-text-muted">Adv</p>
          </div>
          <div>
            <p className="font-mono text-sm font-semibold text-text-secondary">
              {breadth.unchanged.toLocaleString()}
            </p>
            <p className="text-[10px] text-text-muted">Unch</p>
          </div>
          <div>
            <p className="font-mono text-sm font-semibold text-bearish-text">
              {breadth.declines.toLocaleString()}
            </p>
            <p className="text-[10px] text-text-muted">Dec</p>
          </div>
        </div>

        <p className="text-[10px] text-text-muted text-center mt-auto">
          {isLive ? "NSE" : "Sample"} · {total.toLocaleString()} total
        </p>
      </div>
    </BentoCard>
  );
}
