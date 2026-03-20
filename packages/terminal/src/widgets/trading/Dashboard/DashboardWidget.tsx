// Migrated to TSX — Phase 4 Batch 1
// Replaces direct API calls with TanStack Query hooks (useFunds, usePositions, useOrders).
// Index cards are driven by Jotai tickAtomFamily (populated by useWsBridge in App.tsx).
import { useMemo } from "react";
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
import type { WsTick } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";

// ─── OpenAlgo runtime shapes (snake_case) ────────────────────────────────────
// The typed api.ts interfaces use camelCase but OpenAlgo REST returns snake_case.
// These raw interfaces reflect what we actually receive.
interface RawPosition {
  symbol: string;
  pnl?: string | number;
  average_price?: string | number;
  ltp?: string | number;
  quantity?: string | number;
}

interface RawOrder {
  symbol: string;
  orderId?: string;
  order_id?: string;
  action?: string;
  quantity?: string | number;
  price?: string | number;
  order_status?: string;
  status?: string;
  timestamp?: string;
}

interface RawFunds {
  availablecash?: string | number;
  utiliseddebits?: string | number;
}

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
        <div className="text-lg font-mono font-bold text-text-muted">&mdash;</div>
        <div className="h-4" />
      </div>
    );
  }

  const ltp = tick.ltp ?? 0;
  const prevClose = tick.close ?? 0;
  const change = prevClose > 0 ? ltp - prevClose : 0;
  const changePct = prevClose > 0 ? (change / prevClose) * 100 : 0;
  const up = change >= 0;
  const isVix = name === "VIX";
  const vixHigh = isVix && ltp > 20;

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
        {up ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
        <span className="font-mono tabular-nums">
          {change >= 0 ? "+" : ""}
          {change.toFixed(2)}
        </span>
        <span className="font-mono tabular-nums text-xs">
          ({changePct >= 0 ? "+" : ""}
          {changePct.toFixed(2)}%)
        </span>
      </div>
    </div>
  );
}

// ─── Main widget ──────────────────────────────────────────────────────────────
export default function DashboardWidget(_props: WidgetProps) {
  const { data: fundsData, dataUpdatedAt } = useFunds();
  const { data: positionsData } = usePositions();
  const { data: ordersData } = useOrders();

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
    <div className="h-full overflow-auto p-4 space-y-4">
      {/* Index strip */}
      <div className="grid grid-cols-5 gap-3">
        {INDICES.map((idx) => (
          <IndexCard
            key={idx.symbol}
            atomKey={`${idx.exchange}:${idx.symbol}`}
            name={idx.name}
          />
        ))}
      </div>

      {/* Funds / Margin / P&L cards */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-surface-card border border-border-default rounded-lg p-4 shadow-sm">
          <div className="flex items-center gap-1.5 text-xxs uppercase tracking-wider text-text-muted font-sans mb-2">
            <Wallet size={12} className="text-text-muted" />
            Funds
          </div>
          <div
            className={`text-2xl font-mono font-bold tabular-nums ${
              availableCash >= 0 ? "text-profit" : "text-loss"
            }`}
          >
            {funds ? `\u20B9${INR0.format(availableCash)}` : "\u2014"}
          </div>
        </div>

        <div className="bg-surface-card border border-border-default rounded-lg p-4 shadow-sm">
          <div className="flex items-center gap-1.5 text-xxs uppercase tracking-wider text-text-muted font-sans mb-2">
            <Activity size={12} className="text-text-muted" />
            Margin Used
          </div>
          <div className="text-2xl font-mono font-bold tabular-nums text-text-primary">
            {funds ? `\u20B9${INR0.format(usedMargin)}` : "\u2014"}
          </div>
        </div>

        <div className="bg-surface-card border border-border-default rounded-lg p-4 shadow-sm">
          <div className="flex items-center gap-1.5 text-xxs uppercase tracking-wider text-text-muted font-sans mb-2">
            <BarChart3 size={12} className="text-text-muted" />
            Day P&L
          </div>
          <div
            className={`text-2xl font-mono font-bold tabular-nums ${
              totalPnl >= 0 ? "text-profit" : "text-loss"
            }`}
          >
            {positions.length > 0 || funds
              ? `${totalPnl >= 0 ? "+" : ""}\u20B9${INR0.format(Math.abs(totalPnl))}`
              : "\u2014"}
          </div>
        </div>
      </div>

      {/* Positions section */}
      <div className="bg-surface-card border border-border-default rounded-lg shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border-default">
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Positions
          </h3>
          {lastFetch && (
            <div className="flex items-center gap-1 text-xs text-text-muted font-sans">
              <Clock size={10} />
              {lastFetch.toLocaleTimeString("en-IN", {
                timeZone: "Asia/Kolkata",
                hour12: false,
              })}
            </div>
          )}
        </div>
        {positions.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <Minus size={16} className="mx-auto mb-1 text-text-disabled" />
            <p className="text-xs text-text-muted font-sans">No open positions</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans">
                  Symbol
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right">
                  Qty
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right">
                  Avg
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right">
                  LTP
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right">
                  P&L
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right">
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
                    <TableCell className="font-mono font-medium text-text-primary">
                      {p.symbol}
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono tabular-nums ${
                        qty > 0
                          ? "text-profit"
                          : qty < 0
                            ? "text-loss"
                            : "text-text-secondary"
                      }`}
                    >
                      {qty}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-text-secondary">
                      {INR.format(avg)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-text-primary">
                      {INR.format(ltp)}
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono tabular-nums font-medium ${
                        pnl >= 0 ? "text-profit" : "text-loss"
                      }`}
                    >
                      {pnl >= 0 ? "+" : ""}\u20B9{INR0.format(Math.abs(pnl))}
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono tabular-nums ${
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
        )}
      </div>

      {/* Orders section */}
      <div className="bg-surface-card border border-border-default rounded-lg shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border-default">
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Orders
          </h3>
        </div>
        {orders.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <Minus size={16} className="mx-auto mb-1 text-text-disabled" />
            <p className="text-xs text-text-muted font-sans">No orders today</p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans">
                  Time
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans">
                  Symbol
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-center">
                  Action
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right">
                  Qty
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-right">
                  Price
                </TableHead>
                <TableHead className="text-xxs uppercase tracking-wider text-text-muted font-sans text-center">
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
                  <TableCell className="font-mono tabular-nums text-text-muted">
                    {o.timestamp ?? "\u2014"}
                  </TableCell>
                  <TableCell className="font-mono font-medium text-text-primary">
                    {o.symbol}
                  </TableCell>
                  <TableCell
                    className={`text-center font-sans font-medium ${
                      o.action === "BUY" ? "text-profit" : "text-loss"
                    }`}
                  >
                    {o.action}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums text-text-secondary">
                    {String(o.quantity ?? "")}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums text-text-secondary">
                    {o.price ? String(o.price) : "MKT"}
                  </TableCell>
                  <TableCell className="text-center">
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
        )}
      </div>
    </div>
  );
}
