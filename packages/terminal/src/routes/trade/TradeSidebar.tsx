/**
 * TradeSidebar.tsx
 *
 * Persistent left sidebar for /trade route.
 * Shows a compact Watchlist header (placeholder for next iteration) and a
 * live Positions summary fed from the TanStack Query usePositions hook.
 *
 * Accessibility:
 * - Landmark: <nav> with aria-label
 * - Position rows are a list (role="list") with each row as role="listitem"
 * - P&L values are screen-reader annotated via aria-label
 */

import { SectionHeader } from "@/components/layout/SectionHeader";
import { usePositions } from "@/hooks/usePositions";
import type { Position } from "@/types/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format signed P&L number as a compact integer string (e.g. "+1,234" / "-500"). */
function formatPnl(pnl: number): string {
  const abs = Math.abs(pnl).toFixed(0);
  return pnl >= 0 ? `+${abs}` : `-${abs}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TradeSidebar() {
  const { data: positions, isLoading } = usePositions();

  return (
    <nav
      aria-label="Trade sidebar: Watchlist and Positions"
      className="h-full overflow-y-auto bg-surface-card border-r border-border-default flex flex-col"
    >
      {/* Watchlist section */}
      <section aria-labelledby="sidebar-watchlist-heading" className="p-3 border-b border-border-default">
        <SectionHeader
          title="Watchlist"
          as="h3"
          className="mb-2"
        />
        <p className="text-xs text-text-muted">
          Full watchlist in next iteration
        </p>
      </section>

      {/* Positions section */}
      <section
        aria-labelledby="sidebar-positions-heading"
        className="p-3 flex-1 min-h-0 overflow-y-auto"
      >
        <SectionHeader
          title="Positions"
          as="h3"
          className="mb-2"
        />

        {isLoading && (
          <p className="text-xs text-text-disabled px-1" aria-live="polite">
            Loading...
          </p>
        )}

        {!isLoading && (!positions || positions.length === 0) && (
          <p className="text-xs text-text-disabled px-1">
            No open positions
          </p>
        )}

        {positions && positions.length > 0 && (
          <ul role="list" className="space-y-0.5">
            {(positions as Position[]).slice(0, 10).map((p, i) => {
              const pnl = Number(p.pnl ?? 0);
              const isProfitable = pnl >= 0;
              return (
                <li
                  key={`${p.symbol}-${p.exchange}-${i}`}
                  role="listitem"
                  className="flex justify-between items-center text-xs px-1 py-1 rounded hover:bg-surface-hover transition-colors"
                >
                  <span
                    className="font-mono truncate max-w-[120px] text-text-primary"
                    title={`${p.symbol} (${p.exchange})`}
                  >
                    {p.symbol}
                  </span>
                  <span
                    className={`font-mono tabular-nums shrink-0 ml-1 ${
                      isProfitable ? "text-profit" : "text-loss"
                    }`}
                    aria-label={`P&L ${isProfitable ? "profit" : "loss"} ${Math.abs(pnl).toFixed(0)} rupees`}
                  >
                    {formatPnl(pnl)}
                  </span>
                </li>
              );
            })}

            {positions.length > 10 && (
              <li className="text-xxs text-text-disabled px-1 pt-1">
                +{positions.length - 10} more
              </li>
            )}
          </ul>
        )}
      </section>
    </nav>
  );
}
