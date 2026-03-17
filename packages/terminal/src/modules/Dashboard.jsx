import { useState, useEffect, useCallback } from "react";
import { TrendingUp, TrendingDown, Wallet, Activity, Clock } from "lucide-react";
import { getFunds, getPositionbook, getOrderbook, getQuotes } from "../services/api";

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const INR0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

const INDICES = [
  { symbol: "NIFTY", exchange: "NSE_INDEX", name: "NIFTY 50" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX", name: "BANK NIFTY" },
  { symbol: "SENSEX", exchange: "BSE_INDEX", name: "SENSEX" },
  { symbol: "FINNIFTY", exchange: "NSE_INDEX", name: "FIN NIFTY" },
  { symbol: "INDIA VIX", exchange: "NSE_INDEX", name: "VIX" },
];

function isRefreshWindow() {
  const now = new Date();
  const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const mins = ist.getHours() * 60 + ist.getMinutes();
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  return mins >= 540 && mins <= 945; // 9:00-15:45
}

function IndexCard({ data, name }) {
  if (!data) {
    return (
      <div className="bg-surface-card rounded-lg border border-border-default p-3">
        <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">{name}</div>
        <div className="text-xl font-semibold font-mono text-text-muted">&mdash;</div>
        <div className="text-xs text-text-muted mt-0.5">&mdash;</div>
      </div>
    );
  }

  const ltp = data.ltp ?? 0;
  const prevClose = data.prev_close ?? data.close ?? 0;
  const change = prevClose > 0 ? ltp - prevClose : 0;
  const changePct = prevClose > 0 ? (change / prevClose) * 100 : 0;
  const up = change >= 0;
  const isVix = name === "VIX";
  const vixHigh = isVix && ltp > 20;

  return (
    <div className={`bg-surface-card rounded-lg border p-3 ${vixHigh ? "border-loss/40" : "border-border-default"}`}>
      <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">{name}</div>
      <div className="text-xl font-semibold font-mono text-text-primary">
        {ltp > 0 ? INR.format(ltp) : "—"}
      </div>
      <div className={`flex items-center gap-1 text-xs mt-1 ${up ? "text-profit" : "text-loss"}`}>
        {up ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
        <span className="font-mono">{change >= 0 ? "+" : ""}{change.toFixed(2)}</span>
        <span className="font-mono text-[10px]">({changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%)</span>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [indices, setIndices] = useState({});
  const [funds, setFunds] = useState(null);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [orderStats, setOrderStats] = useState(null);
  const [lastFetch, setLastFetch] = useState(null);

  const fetchAll = useCallback(async () => {
    const promises = INDICES.map(async (idx) => {
      try {
        const data = await getQuotes(idx.symbol, idx.exchange);
        setIndices((prev) => ({ ...prev, [`${idx.exchange}:${idx.symbol}`]: data }));
      } catch { /* API unreachable */ }
    });
    await Promise.allSettled(promises);

    try {
      const f = await getFunds();
      setFunds(f);
    } catch { /* */ }

    try {
      const p = await getPositionbook();
      setPositions(Array.isArray(p) ? p : []);
    } catch { setPositions([]); }

    try {
      const ob = await getOrderbook();
      setOrders(ob?.orders || []);
      setOrderStats(ob?.statistics || null);
    } catch { setOrders([]); }

    setLastFetch(new Date());
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = isRefreshWindow() ? 5000 : 60000;
    const id = setInterval(fetchAll, interval);
    return () => clearInterval(id);
  }, [fetchAll]);

  const availableCash = parseFloat(funds?.availablecash || 0);
  const usedMargin = parseFloat(funds?.utiliseddebits || 0);
  const totalPnl = positions.reduce((s, p) => s + parseFloat(p.pnl || 0), 0);

  return (
    <div className="space-y-3">
      {/* Market indices — 5 columns */}
      <div className="grid grid-cols-5 gap-2">
        {INDICES.map((idx) => (
          <IndexCard key={idx.symbol} data={indices[`${idx.exchange}:${idx.symbol}`]} name={idx.name} />
        ))}
      </div>

      {/* Account metrics — 3 columns */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-surface-card rounded-lg border border-border-default p-3">
          <div className="flex items-center gap-1.5 text-[10px] text-text-muted uppercase tracking-wider mb-2">
            <Wallet size={12} /> Funds
          </div>
          <div className="text-2xl font-semibold font-mono text-profit">
            {funds ? `₹${INR0.format(availableCash)}` : "—"}
          </div>
        </div>

        <div className="bg-surface-card rounded-lg border border-border-default p-3">
          <div className="flex items-center gap-1.5 text-[10px] text-text-muted uppercase tracking-wider mb-2">
            <Activity size={12} /> Margin Used
          </div>
          <div className="text-2xl font-semibold font-mono text-warning">
            {funds ? `₹${INR0.format(usedMargin)}` : "—"}
          </div>
        </div>

        <div className="bg-surface-card rounded-lg border border-border-default p-3">
          <div className="flex items-center gap-1.5 text-[10px] text-text-muted uppercase tracking-wider mb-2">
            <TrendingUp size={12} /> Day P&L
          </div>
          <div className={`text-2xl font-semibold font-mono ${totalPnl >= 0 ? "text-profit" : "text-loss"}`}>
            {positions.length > 0 || funds
              ? `${totalPnl >= 0 ? "+" : ""}₹${INR0.format(Math.abs(totalPnl))}`
              : "—"}
          </div>
        </div>
      </div>

      {/* Positions table */}
      <div className="bg-surface-card rounded-lg border border-border-default">
        <div className="flex items-center justify-between px-3 py-2 border-b border-border-default">
          <h3 className="text-xs text-text-muted uppercase tracking-wider">Positions</h3>
          {lastFetch && (
            <div className="flex items-center gap-1 text-[10px] text-text-muted">
              <Clock size={9} />
              {lastFetch.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </div>
          )}
        </div>
        {positions.length === 0 ? (
          <div className="px-3 py-8 text-center text-text-muted text-sm">No open positions</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] text-text-muted uppercase tracking-wider">
                <th className="px-3 py-2 text-left">Symbol</th>
                <th className="px-3 py-2 text-right">Qty</th>
                <th className="px-3 py-2 text-right">Avg Price</th>
                <th className="px-3 py-2 text-right">LTP</th>
                <th className="px-3 py-2 text-right">P&L</th>
                <th className="px-3 py-2 text-right">P&L%</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => {
                const pnl = parseFloat(p.pnl || 0);
                const avg = parseFloat(p.average_price || 0);
                const ltp = parseFloat(p.ltp || 0);
                const qty = parseInt(p.quantity || 0, 10);
                const pnlPct = avg > 0 && qty !== 0 ? (pnl / (avg * Math.abs(qty))) * 100 : 0;
                return (
                  <tr key={i} className="border-t border-border-subtle hover:bg-surface-hover/50">
                    <td className="px-3 py-1.5 font-medium font-mono text-sm">{p.symbol}</td>
                    <td className={`px-3 py-1.5 text-right font-mono ${qty > 0 ? "text-profit" : qty < 0 ? "text-loss" : ""}`}>{qty}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-text-secondary">{INR.format(avg)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{INR.format(ltp)}</td>
                    <td className={`px-3 py-1.5 text-right font-mono font-medium ${pnl >= 0 ? "text-profit" : "text-loss"}`}>
                      {pnl >= 0 ? "+" : ""}₹{INR0.format(Math.abs(pnl))}
                    </td>
                    <td className={`px-3 py-1.5 text-right font-mono text-xs ${pnlPct >= 0 ? "text-profit" : "text-loss"}`}>
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
      <div className="bg-surface-card rounded-lg border border-border-default">
        <div className="px-3 py-2 border-b border-border-default">
          <h3 className="text-xs text-text-muted uppercase tracking-wider">
            Orders
            {orderStats ? ` — ${orderStats.total_completed_orders || 0} filled, ${orderStats.total_open_orders || 0} open` : ""}
          </h3>
        </div>
        {orders.length === 0 ? (
          <div className="px-3 py-8 text-center text-text-muted text-sm">No orders today</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] text-text-muted uppercase tracking-wider">
                <th className="px-3 py-2 text-left">Time</th>
                <th className="px-3 py-2 text-left">Symbol</th>
                <th className="px-3 py-2 text-center">Action</th>
                <th className="px-3 py-2 text-right">Qty</th>
                <th className="px-3 py-2 text-right">Price</th>
                <th className="px-3 py-2 text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o, i) => (
                <tr key={i} className="border-t border-border-subtle hover:bg-surface-hover/50">
                  <td className="px-3 py-1.5 text-text-muted text-xs font-mono">{o.timestamp || "—"}</td>
                  <td className="px-3 py-1.5 font-medium font-mono text-sm">{o.symbol}</td>
                  <td className={`px-3 py-1.5 text-center font-medium text-xs ${o.action === "BUY" ? "text-profit" : "text-loss"}`}>{o.action}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{o.quantity}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{o.price || "MKT"}</td>
                  <td className="px-3 py-1.5 text-center">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      o.order_status === "complete" ? "bg-profit/10 text-profit" :
                      o.order_status === "rejected" ? "bg-loss/10 text-loss" :
                      "bg-warning/10 text-warning"
                    }`}>{o.order_status || o.status || "—"}</span>
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
