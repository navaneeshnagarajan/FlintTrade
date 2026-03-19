// Migrated to TSX — Phase 4 Batch 1
// Replaces direct API calls with TanStack Query hooks (useFunds, usePositions, useOrders).
// Index cards are driven by Jotai tickAtomFamily (populated by useWsBridge in App.tsx).
import { useMemo } from "react";
import { useAtomValue } from "jotai";
import { TrendingUp, TrendingDown, Wallet, Activity, Clock } from "lucide-react";
import { useFunds } from "@/hooks/useFunds";
import { usePositions } from "@/hooks/usePositions";
import { useOrders } from "@/hooks/useOrders";
import { tickAtomFamily } from "@/atoms/marketAtoms";
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

// ─── IndexCard ────────────────────────────────────────────────────────────────
interface IndexCardProps {
  atomKey: string;
  name: string;
}

function IndexCard({ atomKey, name }: IndexCardProps) {
  const tick: WsTick | null = useAtomValue(tickAtomFamily(atomKey));

  if (!tick) {
    return (
      <div className="bg-surface-card rounded border border-border-default p-2">
        <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">{name}</div>
        <div className="text-lg font-semibold font-mono text-text-muted">&mdash;</div>
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
    <div className={`bg-surface-card rounded border p-2 ${vixHigh ? "border-loss/40" : "border-border-default"}`}>
      <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">{name}</div>
      <div className="text-lg font-semibold font-mono text-text-primary">
        {ltp > 0 ? INR.format(ltp) : "—"}
      </div>
      <div className={`flex items-center gap-1 text-xs mt-0.5 ${up ? "text-profit" : "text-loss"}`}>
        {up ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
        <span className="font-mono">{change >= 0 ? "+" : ""}{change.toFixed(2)}</span>
        <span className="font-mono text-[10px]">({changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%)</span>
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
    <div className="h-full overflow-auto p-3 space-y-3">
      {/* Index strip */}
      <div className="grid grid-cols-5 gap-2">
        {INDICES.map((idx) => (
          <IndexCard
            key={idx.symbol}
            atomKey={`${idx.exchange}:${idx.symbol}`}
            name={idx.name}
          />
        ))}
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-surface-card rounded border border-border-default p-2">
          <div className="flex items-center gap-1 text-[10px] text-text-muted uppercase tracking-wider mb-1">
            <Wallet size={11} /> Funds
          </div>
          <div className="text-xl font-semibold font-mono text-profit">
            {funds ? `₹${INR0.format(availableCash)}` : "—"}
          </div>
        </div>
        <div className="bg-surface-card rounded border border-border-default p-2">
          <div className="flex items-center gap-1 text-[10px] text-text-muted uppercase tracking-wider mb-1">
            <Activity size={11} /> Margin Used
          </div>
          <div className="text-xl font-semibold font-mono text-warning">
            {funds ? `₹${INR0.format(usedMargin)}` : "—"}
          </div>
        </div>
        <div className="bg-surface-card rounded border border-border-default p-2">
          <div className="flex items-center gap-1 text-[10px] text-text-muted uppercase tracking-wider mb-1">
            <TrendingUp size={11} /> Day P&L
          </div>
          <div className={`text-xl font-semibold font-mono ${totalPnl >= 0 ? "text-profit" : "text-loss"}`}>
            {positions.length > 0 || funds
              ? `${totalPnl >= 0 ? "+" : ""}₹${INR0.format(Math.abs(totalPnl))}`
              : "—"}
          </div>
        </div>
      </div>

      {/* Positions table */}
      <div className="bg-surface-card rounded border border-border-default">
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default">
          <h3 className="text-[10px] text-text-muted uppercase tracking-wider">Positions</h3>
          {lastFetch && (
            <div className="flex items-center gap-1 text-[10px] text-text-muted">
              <Clock size={9} />
              {lastFetch.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </div>
          )}
        </div>
        {positions.length === 0 ? (
          <div className="px-3 py-6 text-center text-text-muted text-xs">No open positions</div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] text-text-muted uppercase tracking-wider">
                <th className="px-3 py-1.5 text-left">Symbol</th>
                <th className="px-3 py-1.5 text-right">Qty</th>
                <th className="px-3 py-1.5 text-right">Avg</th>
                <th className="px-3 py-1.5 text-right">LTP</th>
                <th className="px-3 py-1.5 text-right">P&L</th>
                <th className="px-3 py-1.5 text-right">P&L%</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => {
                const pnl = parseFloat(String(p.pnl ?? 0));
                const avg = parseFloat(String(p.average_price ?? 0));
                const ltp = parseFloat(String(p.ltp ?? 0));
                const qty = parseInt(String(p.quantity ?? 0), 10);
                const pnlPct = avg > 0 && qty !== 0 ? (pnl / (avg * Math.abs(qty))) * 100 : 0;
                return (
                  <tr key={p.symbol || String(i)} className="border-t border-border-subtle hover:bg-surface-hover/50">
                    <td className="px-3 py-1 font-medium font-mono">{p.symbol}</td>
                    <td className={`px-3 py-1 text-right font-mono ${qty > 0 ? "text-profit" : qty < 0 ? "text-loss" : ""}`}>{qty}</td>
                    <td className="px-3 py-1 text-right font-mono text-text-secondary">{INR.format(avg)}</td>
                    <td className="px-3 py-1 text-right font-mono">{INR.format(ltp)}</td>
                    <td className={`px-3 py-1 text-right font-mono font-medium ${pnl >= 0 ? "text-profit" : "text-loss"}`}>
                      {pnl >= 0 ? "+" : ""}₹{INR0.format(Math.abs(pnl))}
                    </td>
                    <td className={`px-3 py-1 text-right font-mono text-[10px] ${pnlPct >= 0 ? "text-profit" : "text-loss"}`}>
                      {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Orders table */}
      <div className="bg-surface-card rounded border border-border-default">
        <div className="px-3 py-1.5 border-b border-border-default">
          <h3 className="text-[10px] text-text-muted uppercase tracking-wider">Orders</h3>
        </div>
        {orders.length === 0 ? (
          <div className="px-3 py-6 text-center text-text-muted text-xs">No orders today</div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] text-text-muted uppercase tracking-wider">
                <th className="px-3 py-1.5 text-left">Time</th>
                <th className="px-3 py-1.5 text-left">Symbol</th>
                <th className="px-3 py-1.5 text-center">Action</th>
                <th className="px-3 py-1.5 text-right">Qty</th>
                <th className="px-3 py-1.5 text-right">Price</th>
                <th className="px-3 py-1.5 text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o, i) => (
                <tr key={o.orderId ?? o.order_id ?? (o.symbol + (o.timestamp ?? "") + String(i))} className="border-t border-border-subtle hover:bg-surface-hover/50">
                  <td className="px-3 py-1 text-text-muted font-mono">{o.timestamp ?? "—"}</td>
                  <td className="px-3 py-1 font-medium font-mono">{o.symbol}</td>
                  <td className={`px-3 py-1 text-center font-medium ${o.action === "BUY" ? "text-profit" : "text-loss"}`}>{o.action}</td>
                  <td className="px-3 py-1 text-right font-mono">{String(o.quantity ?? "")}</td>
                  <td className="px-3 py-1 text-right font-mono">{o.price ? String(o.price) : "MKT"}</td>
                  <td className="px-3 py-1 text-center">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      o.order_status === "complete" ? "bg-profit/10 text-profit" :
                      o.order_status === "rejected" ? "bg-loss/10 text-loss" :
                      "bg-warning/10 text-warning"
                    }`}>{o.order_status ?? o.status ?? "—"}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
