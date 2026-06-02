// Migrated to TSX — Phase 4 Batch 1
// Replaces direct API calls with TanStack Query hooks (useFunds, usePositions, useOrders).
// Index cards are driven by Jotai tickAtomFamily (populated by useWsBridge in App.tsx).
import { useMemo, memo } from "react";
import { useAtomValue } from "jotai";
import {
  TrendingUp,
  TrendingDown,
  Wallet,
  Activity,
  Clock,
  BarChart3,
  Minus,
} from "lucide-react";
import { FlintMiniSparkline, FlintSegmentTracker } from "@flinttrade/design-system";
import { useFunds } from "@/hooks/useFunds";
import { usePositions } from "@/hooks/usePositions";
import { useOrders } from "@/hooks/useOrders";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { WsTick } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";
import type { RawPosition, RawOrder, RawFunds } from "@/types/rawApi";

// ─── Constants ────────────────────────────────────────────────────────────────
const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const INR0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

interface IndexDef {
  symbol: string;
  exchange: string;
  name: string;
}

const INDICES: IndexDef[] = [
  { symbol: "NIFTY", exchange: "NSE_INDEX", name: "NIFTY 50" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX", name: "BANK NIFTY" },
  { symbol: "SENSEX", exchange: "BSE_INDEX", name: "SENSEX" },
  { symbol: "FINNIFTY", exchange: "NSE_INDEX", name: "FIN NIFTY" },
  { symbol: "INDIAVIX", exchange: "NSE_INDEX", name: "VIX" },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────
function getOrderStatusVariant(
  status: string | undefined,
): "bullish" | "bearish" | "neutral" {
  if (!status) return "neutral";
  const s = status.toLowerCase();
  if (s === "complete" || s === "completed" || s === "filled") return "bullish";
  if (s === "rejected" || s === "cancelled" || s === "canceled") return "bearish";
  return "neutral";
}

// ─── IndexCard ────────────────────────────────────────────────────────────────
interface IndexCardProps {
  atomKey: string;
  name: string;
}

function IndexCard({ atomKey, name }: IndexCardProps) {
  const tick: WsTick | null = useAtomValue(tickAtomFamily(atomKey));

  if (!tick) {
    return (
      <div className="bg-surface-card border border-border-default rounded-lg p-4 shadow-sm">
        <div className="text-xxs uppercase tracking-wider text-text-muted font-sans mb-1.5">
          {name}
        </div>
        <Skeleton className="h-6 w-24 mb-1" />
        <Skeleton className="h-4 w-16 mt-1" />
      </div>
    );
  }

  const ltp = tick.ltp ?? 0;
  // Prefer prevClose (REST-fetched by usePrevClose) — tick.close is undefined
  // in LTP WebSocket mode. Fall back to tick.close for quote/fallback modes.
  const prevClose = tick.prevClose ?? tick.close ?? 0;
  const open = tick.open ?? prevClose;
  const high = tick.high ?? ltp;
  const low = tick.low ?? ltp;
  const change = prevClose > 0 ? ltp - prevClose : 0;
  const changePct = prevClose > 0 ? (change / prevClose) * 100 : 0;
  const up = change >= 0;
  const isVix = name === "VIX";
  const vixHigh = isVix && ltp > 20;

  // Build a 5-point OHLC sparkline from the available tick data
  const sparkData = [open, low, (open + ltp) / 2, high, ltp];

  return (
    <div
      className={`bg-surface-card border rounded-lg p-4 shadow-sm ${
        vixHigh ? "border-loss/40" : "border-border-default"
      }`}
    >
      <div className="text-xxs uppercase tracking-wider text-text-muted font-sans mb-1.5">
        {name}
      </div>
      <div className="text-lg font-mono font-bold text-text-primary">
        {ltp > 0 ? INR.format(ltp) : "\u2014"}
      </div>
      <div
        className={`flex items-center gap-1 text-xs mt-1 ${
          up ? "text-profit" : "text-loss"
        }`}
      >
        {up ? <TrendingUp size={11} aria-hidden="true" /> : <TrendingDown size={11} aria-hidden="true" />}
        <span className="font-mono tabular-nums">
          {change >= 0 ? "+" : ""}
          {change.toFixed(2)}
        </span>
        <span className="font-mono tabular-nums text-xs">
          ({changePct >= 0 ? "+" : ""}
          {changePct.toFixed(2)}%)
        </span>
      </div>
      {ltp > 0 && (
        <FlintMiniSparkline
          ariaLabel={`${name} OHLC sparkline`}
          points={sparkData}
          positive={up}
          className="mt-2 h-8"
        />
      )}
    </div>
  );
}

// ─── Main widget ──────────────────────────────────────────────────────────────
function DashboardWidget(_props: WidgetProps) {
  const { data: fundsData, dataUpdatedAt, isPending: fundsPending } = useFunds();
  const { data: positionsData, isPending: positionsPending } = usePositions();
  const { data: ordersData, isPending: ordersPending } = useOrders();

  const funds = fundsData as RawFunds | undefined;
  const positions = (positionsData ?? []) as RawPosition[];
  const orders = (ordersData ?? []) as RawOrder[];

  const availableCash = parseFloat(String(funds?.availablecash ?? 0));
  const usedMargin = parseFloat(String(funds?.utiliseddebits ?? 0));

  const totalPnl = useMemo(
    () => positions.reduce((s, p) => s + parseFloat(String(p.pnl ?? 0)), 0),
    [positions],
  );

  const lastFetch = dataUpdatedAt ? new Date(dataUpdatedAt) : null;

  return (
    <div className="h-full w-full flex flex-col overflow-hidden bg-surface-base" data-tour-target="dashboard">
      <h2 className="sr-only">Dashboard Overview</h2>
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
      {/* Index strip — responsive: 5 cols on wide panels, fewer on narrow */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {INDICES.map((idx) => (
          <IndexCard
            key={idx.symbol}
            atomKey={`${idx.exchange}:${idx.symbol}`}
            name={idx.name}
          />
        ))}
      </div>

      {/* Funds / Margin / P&L cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-surface-card border border-border-default rounded-lg p-4 shadow-sm">
          <div className="flex items-center gap-1.5 text-xxs uppercase tracking-wider text-text-muted font-sans mb-2">
            <Wallet size={12} className="text-text-muted" aria-hidden="true" />
            Funds
          </div>
          <div
            className={`text-2xl font-mono font-bold tabular-nums ${
              availableCash >= 0 ? "text-profit" : "text-loss"
            }`}
          >
            {fundsPending ? (
              <Skeleton className="h-7 w-28" />
            ) : funds ? (
              `\u20B9${INR0.format(availableCash)}`
            ) : (
              "\u2014"
            )}
          </div>
        </div>

        <div className="bg-surface-card border border-border-default rounded-lg p-4 shadow-sm">
          <div className="flex items-center gap-1.5 text-xxs uppercase tracking-wider text-text-muted font-sans mb-2">
            <Activity size={12} className="text-text-muted" aria-hidden="true" />
            Margin Used
          </div>
          <div className="text-2xl font-mono font-bold tabular-nums text-text-primary">
            {fundsPending ? (
              <Skeleton className="h-7 w-24" />
            ) : funds ? (
              `\u20B9${INR0.format(usedMargin)}`
            ) : (
              "\u2014"
            )}
          </div>
        </div>

        <div className="bg-surface-card border border-border-default rounded-lg p-4 shadow-sm">
          <div className="flex items-center gap-1.5 text-xxs uppercase tracking-wider text-text-muted font-sans mb-2">
            <BarChart3 size={12} className="text-text-muted" aria-hidden="true" />
            Day P&L
          </div>
          <div
            className={`text-2xl font-mono font-bold tabular-nums ${
              totalPnl >= 0 ? "text-profit" : "text-loss"
            }`}
          >
            {positionsPending ? (
              <Skeleton className="h-7 w-28" />
            ) : positions.length > 0 || funds ? (
              `${totalPnl >= 0 ? "+" : ""}\u20B9${INR0.format(Math.abs(totalPnl))}`
            ) : (
              "\u2014"
            )}
          </div>
        </div>
      </div>

      {/* Position status tracker */}
      {positions.length > 0 && (() => {
        const trackerData = positions.map((p) => {
          const pnl = parseFloat(String(p.pnl ?? 0));
          return {
            key: p.symbol,
            label: `${p.symbol}: ${pnl >= 0 ? "+" : ""}₹${Math.abs(pnl).toFixed(0)}`,
            tone: pnl > 0 ? ("profit" as const) : pnl < 0 ? ("loss" as const) : ("neutral" as const),
          };
        });
        return (
          <div className="bg-surface-card border border-border-default rounded-lg px-4 py-3 shadow-sm">
            <div className="text-xxs uppercase tracking-wider text-text-muted font-sans mb-2">
              Position Status
            </div>
            <FlintSegmentTracker
              ariaLabel="Position status tracker"
              segments={trackerData}
            />
            <div className="flex gap-4 mt-1.5 text-xxs text-text-muted">
              <span className="text-emerald-400">{positions.filter((p) => parseFloat(String(p.pnl ?? 0)) > 0).length} profit</span>
              <span className="text-red-400">{positions.filter((p) => parseFloat(String(p.pnl ?? 0)) < 0).length} loss</span>
              <span>{positions.filter((p) => parseFloat(String(p.pnl ?? 0)) === 0).length} flat</span>
            </div>
          </div>
        );
      })()}

      {/* Positions section */}
      <div className="bg-surface-card border border-border-default rounded-lg shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border-default">
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Positions
          </h3>
          {lastFetch && (
            <div className="flex items-center gap-1 text-xs text-text-muted font-sans">
              <Clock size={10} aria-hidden="true" />
              {lastFetch.toLocaleTimeString("en-IN", {
                timeZone: "Asia/Kolkata",
                hour12: false,
              })}
            </div>
          )}
        </div>
        {positionsPending ? (
          <div className="p-4 space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : positions.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <Minus size={16} className="mx-auto mb-1 text-text-disabled" aria-hidden="true" />
            <p className="text-xs text-text-muted font-sans">No open positions</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans whitespace-nowrap">
                  Symbol
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right whitespace-nowrap">
                  Qty
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right whitespace-nowrap">
                  Avg
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right whitespace-nowrap">
                  LTP
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right whitespace-nowrap">
                  P&L
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right whitespace-nowrap">
                  P&L%
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.map((p, i) => {
                const pnl = parseFloat(String(p.pnl ?? 0));
                const avg = parseFloat(String(p.average_price ?? 0));
                const ltp = parseFloat(String(p.ltp ?? 0));
                const qty = parseInt(String(p.quantity ?? 0), 10);
                const pnlPct =
                  avg > 0 && qty !== 0
                    ? (pnl / (avg * Math.abs(qty))) * 100
                    : 0;
                return (
                  <TableRow key={p.symbol || String(i)}>
                    <TableCell className="font-mono font-medium text-text-primary whitespace-nowrap">
                      {p.symbol}
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono tabular-nums whitespace-nowrap ${
                        qty > 0
                          ? "text-profit"
                          : qty < 0
                            ? "text-loss"
                            : "text-text-secondary"
                      }`}
                    >
                      {qty}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-text-secondary whitespace-nowrap">
                      {INR.format(avg)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-text-primary whitespace-nowrap">
                      {INR.format(ltp)}
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono tabular-nums font-medium whitespace-nowrap ${
                        pnl >= 0 ? "text-profit" : "text-loss"
                      }`}
                    >
                      {pnl >= 0 ? "+" : ""}\u20B9{INR0.format(Math.abs(pnl))}
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono tabular-nums whitespace-nowrap ${
                        pnlPct >= 0 ? "text-profit" : "text-loss"
                      }`}
                    >
                      {pnlPct >= 0 ? "+" : ""}
                      {pnlPct.toFixed(2)}%
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          </div>
        )}
      </div>

      {/* Orders section */}
      <div className="bg-surface-card border border-border-default rounded-lg shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border-default">
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Orders
          </h3>
        </div>
        {ordersPending ? (
          <div className="p-4 space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : orders.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <Minus size={16} className="mx-auto mb-1 text-text-disabled" aria-hidden="true" />
            <p className="text-xs text-text-muted font-sans">No orders today</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans whitespace-nowrap">
                  Time
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans whitespace-nowrap">
                  Symbol
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-center whitespace-nowrap">
                  Action
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right whitespace-nowrap">
                  Qty
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right whitespace-nowrap">
                  Price
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-center whitespace-nowrap">
                  Status
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {orders.map((o, i) => (
                <TableRow
                  key={
                    o.orderId ??
                    o.order_id ??
                    o.symbol + (o.timestamp ?? "") + String(i)
                  }
                >
                  <TableCell className="font-mono tabular-nums text-text-muted whitespace-nowrap">
                    {o.timestamp ?? "\u2014"}
                  </TableCell>
                  <TableCell className="font-mono font-medium text-text-primary whitespace-nowrap">
                    {o.symbol}
                  </TableCell>
                  <TableCell
                    className={`text-center font-sans font-medium whitespace-nowrap ${
                      o.action === "BUY" ? "text-profit" : "text-loss"
                    }`}
                  >
                    {o.action}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums text-text-secondary whitespace-nowrap">
                    {String(o.quantity ?? "")}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums text-text-secondary whitespace-nowrap">
                    {o.price ? String(o.price) : "MKT"}
                  </TableCell>
                  <TableCell className="text-center whitespace-nowrap">
                    <Badge
                      variant={getOrderStatusVariant(
                        o.order_status ?? o.status,
                      )}
                      className="text-xxs"
                    >
                      {o.order_status ?? o.status ?? "\u2014"}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}

export default memo(DashboardWidget);
