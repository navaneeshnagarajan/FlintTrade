/**
 * PositionsCard — Live positions from usePositions hook, P&L per position, net total.
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { usePositions } from "@/hooks/usePositions";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { getDemoPositions } from "@/hooks/useModeData";
import {
  resolveAccountQueryUi,
  runGuardedAccountRefetch,
} from "@/lib/accountQueryState";
import { useModeStore } from "@/stores/modeStore";
import { useTradingStore } from "@/stores/tradingStore";
import { DemoBadge } from "./DemoBadge";
import { Loader2 } from "lucide-react";

export function PositionsCard() {
  const isExplore = useModeStore((s) => s.mode === "explore");
  const accountReadsEnabled = useAccountReadsEnabled();
  const query = usePositions({ enabled: accountReadsEnabled });
  const storePnl = useTradingStore((s) => s.totalPnl);

  // Demo mode shows simulated positions; the trading-store P&L mirror isn't fed
  // in explore, so derive the header total from the demo positions themselves.
  const positions = isExplore ? getDemoPositions() : query.data;
  const isError = !isExplore && query.isError;
  const openPositions = positions?.filter((p) => p.quantity !== 0) ?? [];
  const queryUi = resolveAccountQueryUi({
    accountReadsEnabled,
    fetchStatus: query.fetchStatus,
    hasData: openPositions.length > 0,
    isError,
    isExplore,
    isLoading: query.isLoading,
  });
  const totalPnl = isExplore
    ? openPositions.reduce((sum, p) => sum + p.pnl, 0)
    : storePnl;
  const totalPnlPositive = totalPnl >= 0;
  const showPnl =
    isExplore ||
    openPositions.length > 0 ||
    (accountReadsEnabled && !queryUi.isPaused && query.isSuccess);

  return (
    <BentoCard size="tall" label="Open Positions" data-testid="positions-card">
      {isExplore && <DemoBadge />}
      <div className="p-4 h-full flex flex-col gap-3">
        {/* In Explore the absolute DemoBadge occupies the top-right corner, so
            clear it — this is the only home card with header content there. */}
        <div className={`flex items-center justify-between ${isExplore ? "pr-12" : ""}`}>
          <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
            Positions
          </p>
          <span
            className="font-mono text-sm font-semibold"
            style={{
              color: showPnl
                ? totalPnlPositive
                  ? "var(--color-bullish-text)"
                  : "var(--color-bearish-text)"
                : "var(--color-text-muted)",
            }}
          >
            {showPnl
              ? `${totalPnlPositive ? "+" : ""}${totalPnl.toLocaleString("en-IN", {
                  style: "currency",
                  currency: "INR",
                  maximumFractionDigits: 0,
                })}`
              : "—"}
          </span>
        </div>

        {isError && (
          <div
            role="alert"
            className="flex items-center justify-between gap-2 text-[10px] text-loss"
          >
            <span>
              Positions unavailable
              {queryUi.isFrozen ? " — displayed positions are frozen" : ""}
            </span>
            <button
              type="button"
              onClick={() => runGuardedAccountRefetch(queryUi.canRefetch, query.refetch)}
              disabled={!queryUi.canRefetch || query.isFetching}
              className="shrink-0 font-medium underline disabled:opacity-50"
            >
              {query.isFetching ? "Retrying…" : "Retry positions"}
            </button>
          </div>
        )}

        {queryUi.isFrozen && !isError && (
          <p role="status" className="text-[10px] text-warning">
            {queryUi.isPaused
              ? "Offline — displayed positions are frozen"
              : "Broker disconnected — displayed positions are frozen"}
          </p>
        )}

        {queryUi.showInitialLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 size={16} className="animate-spin text-text-muted" aria-label="Loading positions" />
          </div>
        ) : openPositions.length > 0 ? (
          <div className="flex-1 overflow-y-auto space-y-1" style={{ scrollbarWidth: "none" }}>
            {openPositions.map((pos) => {
              const pnlPositive = pos.pnl >= 0;
              return (
                <div
                  key={`${pos.symbol}-${pos.exchange}`}
                  className="flex items-center justify-between py-1.5 px-2 rounded-[8px]"
                  style={{ background: "var(--glass-l2-bg, var(--color-surface-elevated))" }}
                >
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-text-primary truncate">{pos.symbol}</p>
                    <p className="text-[10px] text-text-muted">
                      {pos.quantity > 0 ? "LONG" : "SHORT"} · {Math.abs(pos.quantity)}
                    </p>
                  </div>
                  <div className="text-right shrink-0 ml-2">
                    <p
                      className="font-mono text-xs font-semibold"
                      style={{ color: pnlPositive ? "var(--color-bullish-text)" : "var(--color-bearish-text)" }}
                    >
                      {pnlPositive ? "+" : ""}
                      {pos.pnl.toLocaleString("en-IN", {
                        style: "currency",
                        currency: "INR",
                        maximumFractionDigits: 0,
                      })}
                    </p>
                    <p
                      className="font-mono text-[10px]"
                      style={{ color: pnlPositive ? "var(--color-bullish-text)" : "var(--color-bearish-text)" }}
                    >
                      {pnlPositive ? "+" : ""}{pos.pnlPercent.toFixed(2)}%
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : !isError ? (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-xs text-text-muted">
              {isExplore
                ? "No open positions"
                : queryUi.isPaused
                  ? "Positions unavailable while offline"
                  : accountReadsEnabled
                    ? "No open positions"
                    : "Connect a broker to load positions"}
            </p>
          </div>
        ) : null}
      </div>
    </BentoCard>
  );
}
