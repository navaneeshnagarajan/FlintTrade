/**
 * IndicesTab — index levels for the Market Overview widget.
 *
 * Union of two retired surfaces:
 *   - MarketSummary's index strip: the LIVE portion. Cards read the
 *     per-instrument WebSocket tick atoms (the same source Dashboard and
 *     the Ticker consume) and render an explicit "awaiting tick" state
 *     rather than a fabricated level. (These cards were once a hardcoded
 *     sample with the chip pinned to Sample — that fix is preserved.)
 *   - GlobalIndices: the world-indices table. Its backend endpoint is a
 *     stub that self-declares is_sample_data, so the badge keys off the
 *     response flag, never off connection state, and fails closed when the
 *     flag is absent. A connected user never sees the local sample rows.
 */

import { useState, memo } from "react";
import { useAtomValue } from "jotai";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, RefreshCw, Loader2, Inbox } from "lucide-react";
import { FlintMiniSparkline } from "@flinttrade/design-system";
import { Button } from "@/components/ui/button";
import { getGlobalIndices } from "@/services/ftApi";
import type { GlobalIndexEntry } from "@/services/ftApi";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { tickKeyFor } from "@/lib/market";
import { cn } from "@/lib/utils";
import { ProvChip, SectionHeading } from "../shared";
import { SAMPLE_GLOBAL_INDICES } from "../sampleData";

// ---------------------------------------------------------------------------
// Live NSE index cards (from MarketSummary)
// ---------------------------------------------------------------------------

/**
 * Indices shown in the live strip, read from the WebSocket tick stream.
 */
const LIVE_INDICES: ReadonlyArray<{ symbol: string; exchange: string }> = [
  { symbol: "NIFTY", exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
  { symbol: "NIFTYIT", exchange: "NSE_INDEX" },
  { symbol: "INDIAVIX", exchange: "NSE_INDEX" },
];

interface IndexData {
  symbol: string;
  ltp: number;
  change: number;
  changePct: number;
}

function fmtChange(v: number, pct: number): string {
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)} (${sign}${pct.toFixed(2)}%)`;
}

function IndexCard({ d }: { d: IndexData }) {
  const isUp = d.change >= 0;
  return (
    <div
      className="flex flex-col gap-0.5 bg-surface-hover rounded px-2.5 py-2 min-w-28"
      aria-label={`${d.symbol} ${d.ltp} ${fmtChange(d.change, d.changePct)}`}
    >
      <span className="text-xxs text-text-muted font-medium">{d.symbol}</span>
      <span className="text-sm font-semibold font-mono tabular-nums text-text-primary">
        {d.ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
      </span>
      <span className={cn("text-xxs font-mono tabular-nums", isUp ? "text-profit" : "text-loss")}>
        {fmtChange(d.change, d.changePct)}
      </span>
    </div>
  );
}

/**
 * A single index card backed by the live WebSocket tick stream.
 *
 * Renders an explicit waiting state rather than a fabricated level when no
 * tick has arrived.
 */
function LiveIndexCard({ symbol, exchange }: { symbol: string; exchange: string }) {
  const tick = useAtomValue(tickAtomFamily(tickKeyFor(symbol, exchange)));
  const ltp = tick?.ltp ?? 0;
  // prevClose is REST-fetched; tick.close covers quote/fallback modes.
  const prevClose = tick?.prevClose ?? tick?.close ?? 0;

  if (!tick || ltp <= 0 || prevClose <= 0) {
    return (
      <div
        className="flex flex-col gap-0.5 bg-surface-hover rounded px-2.5 py-2 min-w-28"
        aria-label={`${symbol} awaiting live price`}
      >
        <span className="text-xxs text-text-muted font-medium">{symbol}</span>
        <span className="text-sm font-semibold font-mono text-text-muted">—</span>
        <span className="text-xxs text-text-muted">Awaiting tick</span>
      </div>
    );
  }

  const change = ltp - prevClose;
  return <IndexCard d={{ symbol, ltp, change, changePct: (change / prevClose) * 100 }} />;
}

// ---------------------------------------------------------------------------
// Global indices table (from GlobalIndices)
// ---------------------------------------------------------------------------

const REGIONS = ["India", "US", "Europe", "Asia"] as const;
type Region = (typeof REGIONS)[number];

function Sparkline({ data, positive }: { data: number[]; positive: boolean }) {
  if (data.length < 2) return null;

  return (
    <FlintMiniSparkline
      points={data}
      positive={positive}
      ariaLabel="30-day index sparkline"
      className="h-5 w-[60px]"
    />
  );
}

function IndexRow({ entry }: { entry: GlobalIndexEntry }) {
  const positive = entry.change_pct >= 0;
  const changeClass = positive ? "text-profit" : "text-loss";

  return (
    <tr className="border-b border-border-subtle hover:bg-surface-hover/40 transition-colors">
      <td className="px-2 py-1.5">
        <span className="text-xs font-medium text-text-primary">{entry.name}</span>
      </td>
      <td className="px-2 py-1.5 text-right">
        <span className="text-xs font-mono tabular-nums text-text-primary">
          {entry.ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
        </span>
      </td>
      <td className="px-2 py-1.5 text-right">
        <span className={cn("text-xs font-mono tabular-nums", changeClass)}>
          {positive ? "+" : ""}{entry.change.toFixed(2)}
        </span>
      </td>
      <td className="px-2 py-1.5 text-right">
        <span className={cn("text-xs font-mono tabular-nums font-semibold", changeClass)}>
          {positive ? "+" : ""}{entry.change_pct.toFixed(2)}%
        </span>
      </td>
      <td className="px-2 py-1.5">
        <Sparkline data={entry.history} positive={positive} />
      </td>
    </tr>
  );
}

function RegionHeader({ region }: { region: Region }) {
  return (
    <tr>
      <td
        colSpan={5}
        className="px-2 pt-2 pb-0.5 text-xxs font-semibold uppercase tracking-wider text-text-muted bg-surface-elevated border-b border-border-default"
      >
        {region}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Tab
// ---------------------------------------------------------------------------

function IndicesTab() {
  const isConnected = useBrokerConnected();
  const [isRetrying, setIsRetrying] = useState(false);

  const {
    data: liveData,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["globalIndices"],
    queryFn: getGlobalIndices,
    enabled: isConnected,
    refetchInterval: (query) =>
      isConnected && query.state.data?.is_sample_data === false ? 30_000 : false,
    staleTime: 25_000,
  });

  // When connected, only ever show the live response — never the local
  // SAMPLE constant. But the backend endpoint is itself a hardcoded stub
  // that declares `is_sample_data: true`, so a connected response can STILL
  // be fabricated: the badge must key off the response flag, not off
  // connection state.
  const indices: GlobalIndexEntry[] = isConnected
    ? (liveData?.indices ?? [])
    : SAMPLE_GLOBAL_INDICES;

  // Live affordances fail closed: an omitted flag means unknown provenance.
  const isExplicitlyLive = isConnected && liveData?.is_sample_data === false;
  const isSample = !isExplicitlyLive;

  // A timestamp is a live freshness claim, so unknown/sample responses never
  // render one even if a malformed payload includes it.
  const updatedAt = isExplicitlyLive ? (liveData?.updated_at ?? "") : "";

  const isEmpty = indices.length === 0;

  const retry = async () => {
    setIsRetrying(true);
    try {
      await refetch();
    } finally {
      setIsRetrying(false);
    }
  };

  const byRegion = REGIONS.reduce<Record<Region, GlobalIndexEntry[]>>(
    (acc, r) => {
      acc[r] = indices.filter((e) => e.region === r);
      return acc;
    },
    { India: [], US: [], Europe: [], Asia: [] },
  );

  // A tick for the lead index is the evidence that the strip is live. Each
  // card still renders its own "awaiting tick" state, so a partially-
  // populated strip never claims data it does not have.
  const niftyTick = useAtomValue(
    tickAtomFamily(tickKeyFor(LIVE_INDICES[0].symbol, LIVE_INDICES[0].exchange)),
  );
  const indicesLive = (niftyTick?.ltp ?? 0) > 0;

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">
      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-3">

        {/* NSE index strip — live WebSocket ticks */}
        <section aria-labelledby="mo-nse-indices">
          <SectionHeading id="mo-nse-indices">NSE Indices<ProvChip live={indicesLive} /></SectionHeading>
          <div className="flex gap-2 flex-wrap">
            {LIVE_INDICES.map((idx) => (
              <LiveIndexCard key={idx.symbol} symbol={idx.symbol} exchange={idx.exchange} />
            ))}
          </div>
        </section>

        {/* Global indices table */}
        <section aria-labelledby="mo-global-indices">
          <div className="flex items-center gap-2 mb-1.5">
            <SectionHeading id="mo-global-indices">Global Indices</SectionHeading>
            {/* Honest disclosure — shows whenever the rows on screen are
                fabricated: the local SAMPLE constant (disconnected) OR a
                backend payload flagged is_sample_data (the endpoint is
                currently a stub even for connected users). */}
            {isSample && (
              <span
                className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400 mb-1.5"
                role="status"
                aria-label="Showing sample global indices or data with unknown provenance, not verified live prices"
                title="These index values are sample data or have unknown provenance, not verified live prices — do not base trading decisions on them."
              >
                Sample data
              </span>
            )}
            <div className="flex-1" />
            {isExplicitlyLive && !isLoading && !isError && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void refetch()}
                disabled={isFetching}
                className="h-6 w-6 p-0 text-text-muted hover:text-text-primary disabled:opacity-40"
                aria-label="Refresh global indices"
              >
                <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} aria-hidden="true" />
              </Button>
            )}
          </div>

          {/* Loading */}
          {isConnected && isLoading && (
            <div className="flex items-center justify-center gap-2 py-8 text-text-muted text-sm">
              <Loader2 size={14} className="animate-spin" aria-hidden="true" />
              {isRetrying ? "Retrying global indices..." : "Loading indices..."}
            </div>
          )}

          {/* Request failure is distinct from a successful empty response. */}
          {isConnected && !isLoading && isError && (
            <div
              className="flex flex-col items-center justify-center gap-2 py-8 px-4 text-center"
              role="alert"
            >
              <AlertCircle size={18} className="text-loss" aria-hidden="true" />
              <span className="text-sm font-medium text-text-primary">Could not load global indices</span>
              <span className="text-xs text-text-muted">
                {error instanceof Error ? error.message : "The request failed."}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void retry()}
                disabled={isRetrying}
                className="mt-1 h-7 px-2 text-xs"
                aria-label="Retry global indices"
              >
                <RefreshCw size={12} className={isRetrying ? "animate-spin" : ""} aria-hidden="true" />
                {isRetrying ? "Retrying..." : "Retry"}
              </Button>
            </div>
          )}

          {/* Honest empty state — connected but the live response had no
              indices. A connected (live) user must never see fabricated
              sample rows. */}
          {!isLoading && !isError && isEmpty && (
            <div className="flex flex-col items-center justify-center gap-2 py-8 text-text-muted text-sm px-4 text-center">
              <Inbox size={18} aria-hidden="true" />
              <span>No global indices available</span>
            </div>
          )}

          {/* Table */}
          {!isLoading && !isError && !isEmpty && (
            <div className="overflow-auto">
              <table className="w-full border-collapse" aria-label="Global market indices">
                <thead>
                  <tr className="border-b border-border-default sticky top-0 bg-surface-card z-10">
                    <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-left">Index</th>
                    <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-right">LTP</th>
                    <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-right">Chg</th>
                    <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted text-right">Chg%</th>
                    <th className="px-2 py-1.5 text-xxs font-medium uppercase tracking-wide text-text-muted">Trend</th>
                  </tr>
                </thead>
                <tbody>
                  {REGIONS.flatMap((region) =>
                    byRegion[region].length > 0
                      ? [
                          <RegionHeader key={`hdr-${region}`} region={region} />,
                          ...byRegion[region].map((entry) => (
                            <IndexRow key={entry.id} entry={entry} />
                          )),
                        ]
                      : [],
                  )}
                </tbody>
              </table>

              {/* Footer — sample payloads carry no timestamp, so never invent one. */}
              <div className="px-2 py-1.5 text-xxs text-text-muted border-t border-border-subtle">
                {updatedAt && (
                  <>
                    Updated: {new Date(updatedAt).toLocaleTimeString("en-IN", {
                      timeZone: "Asia/Kolkata",
                      hour: "2-digit",
                      minute: "2-digit",
                      hour12: false,
                    })} IST
                  </>
                )}
                {isSample && (
                  <span className={updatedAt ? "ml-2 text-accent/70" : "text-accent/70"}>
                    (sample data)
                  </span>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export default memo(IndicesTab);
