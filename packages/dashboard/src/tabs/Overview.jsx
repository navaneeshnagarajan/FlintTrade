import { useState, useEffect } from "react";
import { getFunds, getPositionbook, getOrderbook, getTradebook, getQuotes } from "../services/api";
import StatCard from "../components/StatCard";
import MiniChart from "../components/MiniChart";

const INDICES = [
  { symbol: "NIFTY", exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
  { symbol: "SENSEX", exchange: "BSE_INDEX" },
  { symbol: "FINNIFTY", exchange: "NSE_INDEX" },
];

function fmtINR(v) {
  const n = Number(v) || 0;
  const sign = n >= 0 ? "+" : "";
  return sign + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function pnlColor(v) {
  const n = Number(v) || 0;
  if (n > 0) return "text-emerald-400";
  if (n < 0) return "text-red-400";
  return "text-gray-400";
}

function StatusBadge({ status }) {
  const map = {
    complete: "bg-emerald-500/20 text-emerald-400",
    completed: "bg-emerald-500/20 text-emerald-400",
    pending: "bg-yellow-500/20 text-yellow-400",
    open: "bg-yellow-500/20 text-yellow-400",
    rejected: "bg-red-500/20 text-red-400",
    cancelled: "bg-gray-500/20 text-gray-400",
  };
  const cls = map[status?.toLowerCase()] || "bg-gray-500/20 text-gray-400";
  return <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${cls}`}>{status}</span>;
}

export default function Overview() {
  const [funds, setFunds] = useState(null);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [trades, setTrades] = useState([]);
  const [indices, setIndices] = useState([]);

  useEffect(() => {
    (async () => {
      try { const d = await getFunds(); setFunds(d); } catch { /* */ }
      try { const d = await getPositionbook(); setPositions(d?.data || d?.positions || []); } catch { /* */ }
      try { const d = await getOrderbook(); setOrders(d?.data || d?.orders || []); } catch { /* */ }
      try { const d = await getTradebook(); setTrades(d?.data || d?.trades || []); } catch { /* */ }
    })();
  }, []);

  useEffect(() => {
    (async () => {
      const results = [];
      for (const idx of INDICES) {
        try {
          const q = await getQuotes(idx.symbol, idx.exchange);
          results.push({ ...idx, ltp: q?.ltp || 0, close: q?.prev_close || q?.close || 0 });
        } catch {
          results.push({ ...idx, ltp: 0, close: 0 });
        }
      }
      setIndices(results);
    })();
  }, []);

  const totalPnL = positions.reduce((s, p) => s + (Number(p.pnl) || 0), 0);
  const openCount = positions.filter((p) => Number(p.quantity) !== 0).length;
  const usedMargin = Number(funds?.used_margin || 0);
  const available = Number(funds?.available_balance || 0);
  const total = Number(funds?.total_balance || 0) || (usedMargin + available) || 1;
  const marginPct = total > 0 ? ((usedMargin / total) * 100).toFixed(1) : "0";
  const wins = trades.filter((t) => Number(t.pnl) > 0).length;
  const winRate = trades.length > 0 ? ((wins / trades.length) * 100).toFixed(0) : "0";

  return (
    <div className="space-y-4">
      {/* Portfolio summary */}
      <div className="grid grid-cols-4 gap-3">
        <StatCard
          title="Today's P&L"
          value={`₹${fmtINR(totalPnL)}`}
          color={pnlColor(totalPnL)}
          trend={totalPnL > 0 ? "up" : totalPnL < 0 ? "down" : undefined}
          subtitle="Realized + Unrealized"
        />
        <StatCard
          title="Open Positions"
          value={openCount}
          subtitle={`Margin used: ₹${fmtINR(usedMargin)}`}
        />
        <StatCard
          title="Available Funds"
          value={`₹${fmtINR(available)}`}
          subtitle={`Margin utilization: ${marginPct}%`}
        />
        <StatCard
          title="Trades Today"
          value={trades.length}
          subtitle={`Win rate: ${winRate}%`}
        />
      </div>

      {/* Market overview */}
      <div className="grid grid-cols-4 gap-3">
        {indices.map((idx) => {
          const change = idx.close > 0 ? (((idx.ltp - idx.close) / idx.close) * 100).toFixed(2) : "0.00";
          const up = Number(change) >= 0;
          const spark = Array.from({ length: 20 }, (_, i) => ({ value: idx.ltp + (Math.random() - 0.5) * idx.ltp * 0.002 * (i + 1) }));
          return (
            <div key={idx.symbol} className="bg-gray-900 rounded-lg border border-gray-800 p-3">
              <div className="flex justify-between items-start mb-1">
                <span className="text-xs font-semibold">{idx.symbol}</span>
                <span className={`text-[10px] font-mono ${up ? "text-emerald-400" : "text-red-400"}`}>
                  {up ? "+" : ""}{change}%
                </span>
              </div>
              <div className="text-lg font-bold font-mono">{idx.ltp ? idx.ltp.toLocaleString("en-IN") : "—"}</div>
              <MiniChart data={spark} color={up ? "#22c55e" : "#ef4444"} height={32} />
            </div>
          );
        })}
      </div>

      {/* Active positions */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-auto">
        <div className="px-3 py-2 border-b border-gray-800 text-xs font-semibold text-gray-400">Active Positions</div>
        <table className="w-full text-xs">
          <thead className="bg-gray-800">
            <tr className="text-gray-400">
              <th className="px-3 py-2 text-left">Symbol</th>
              <th className="px-3 py-2 text-left">Exchange</th>
              <th className="px-3 py-2 text-right">Qty</th>
              <th className="px-3 py-2 text-right">Avg Price</th>
              <th className="px-3 py-2 text-right">LTP</th>
              <th className="px-3 py-2 text-right">P&L</th>
              <th className="px-3 py-2 text-right">P&L%</th>
              <th className="px-3 py-2 text-left">Product</th>
            </tr>
          </thead>
          <tbody>
            {positions.filter((p) => Number(p.quantity) !== 0).map((p, i) => {
              const pnl = Number(p.pnl) || 0;
              const avg = Number(p.average_price) || 0;
              const qty = Number(p.quantity) || 0;
              const pnlPct = avg > 0 && qty !== 0 ? ((pnl / (avg * Math.abs(qty))) * 100).toFixed(2) : "0.00";
              return (
                <tr key={i} className="border-t border-gray-800 hover:bg-gray-800/30">
                  <td className="px-3 py-1.5 font-semibold">{p.symbol}</td>
                  <td className="px-3 py-1.5 text-gray-400">{p.exchange}</td>
                  <td className={`px-3 py-1.5 text-right font-mono ${qty > 0 ? "text-emerald-400" : "text-red-400"}`}>{qty}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{avg.toFixed(2)}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{Number(p.ltp || 0).toFixed(2)}</td>
                  <td className={`px-3 py-1.5 text-right font-mono ${pnlColor(pnl)}`}>{fmtINR(pnl)}</td>
                  <td className={`px-3 py-1.5 text-right font-mono ${pnlColor(pnl)}`}>{pnlPct}%</td>
                  <td className="px-3 py-1.5 text-gray-400">{p.product}</td>
                </tr>
              );
            })}
            {positions.filter((p) => Number(p.quantity) !== 0).length === 0 && (
              <tr><td colSpan={8} className="px-3 py-4 text-center text-gray-500">No open positions</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Recent orders */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-auto">
        <div className="px-3 py-2 border-b border-gray-800 text-xs font-semibold text-gray-400">Recent Orders</div>
        <table className="w-full text-xs">
          <thead className="bg-gray-800">
            <tr className="text-gray-400">
              <th className="px-3 py-2 text-left">Order ID</th>
              <th className="px-3 py-2 text-left">Symbol</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2 text-right">Qty</th>
              <th className="px-3 py-2 text-right">Price</th>
              <th className="px-3 py-2 text-left">Type</th>
              <th className="px-3 py-2 text-center">Status</th>
            </tr>
          </thead>
          <tbody>
            {orders.slice(0, 10).map((o, i) => (
              <tr key={i} className="border-t border-gray-800 hover:bg-gray-800/30">
                <td className="px-3 py-1.5 font-mono text-gray-400">{o.orderid || "—"}</td>
                <td className="px-3 py-1.5 font-semibold">{o.symbol}</td>
                <td className={`px-3 py-1.5 text-center ${o.action === "BUY" ? "text-emerald-400" : "text-red-400"}`}>{o.action}</td>
                <td className="px-3 py-1.5 text-right font-mono">{o.quantity}</td>
                <td className="px-3 py-1.5 text-right font-mono">{o.price || o.average_price || "—"}</td>
                <td className="px-3 py-1.5 text-gray-400">{o.pricetype}</td>
                <td className="px-3 py-1.5 text-center"><StatusBadge status={o.status} /></td>
              </tr>
            ))}
            {orders.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-4 text-center text-gray-500">No orders today</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
