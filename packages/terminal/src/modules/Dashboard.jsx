import { useState, useEffect, useCallback } from "react";
import { TrendingUp, TrendingDown, Wallet, ShoppingCart, Activity, Clock } from "lucide-react";
import { getFunds, getPositionbook, getOrderbook, getQuotes } from "../services/api";

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const INR0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

const INDICES = [
  { symbol: "NIFTY", exchange: "NSE_INDEX", name: "NIFTY 50" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX", name: "BANK NIFTY" },
  { symbol: "SENSEX", exchange: "BSE_INDEX", name: "SENSEX" },
  { symbol: "INDIA VIX", exchange: "NSE_INDEX", name: "VIX" },
];

function IndexCard({ data, name }) {
  if (!data) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">{name}</div>
        <div className="text-2xl font-bold font-mono text-gray-600">&mdash;</div>
        <div className="text-sm text-gray-600 mt-1">Loading...</div>
      </div>
    );
  }

  const ltp = data.ltp ?? 0;
  const prevClose = data.prev_close ?? 0;
  const change = prevClose > 0 ? ltp - prevClose : 0;
  const changePct = prevClose > 0 ? (change / prevClose) * 100 : 0;
  const up = change >= 0;
  const isVix = name === "VIX";
  const vixHigh = isVix && ltp > 20;

  return (
    <div className={`bg-gray-900 rounded-xl border p-5 ${vixHigh ? "border-red-500/40" : "border-gray-800"}`}>
      <div className="text-xs text-gray-500 uppercase tracking-wide mb-2">{name}</div>
      <div className="text-2xl font-bold font-mono">{ltp > 0 ? INR.format(ltp) : "0.00"}</div>
      <div className={`flex items-center gap-1.5 text-sm mt-2 ${up ? "text-emerald-400" : "text-red-400"}`}>
        {up ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
        <span className="font-mono">{change >= 0 ? "+" : ""}{change.toFixed(2)}</span>
        <span className="font-mono text-xs">({changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%)</span>
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
    // Fetch indices via REST quotes
    for (const idx of INDICES) {
      try {
        const data = await getQuotes(idx.symbol, idx.exchange);
        setIndices((prev) => ({ ...prev, [`${idx.exchange}:${idx.symbol}`]: data }));
      } catch { /* API unreachable */ }
    }

    // Fetch funds
    try {
      const f = await getFunds();
      setFunds(f);
    } catch { /* */ }

    // Fetch positions
    try {
      const p = await getPositionbook();
      setPositions(Array.isArray(p) ? p : []);
    } catch { setPositions([]); }

    // Fetch orders
    try {
      const ob = await getOrderbook();
      setOrders(ob?.orders || []);
      setOrderStats(ob?.statistics || null);
    } catch { setOrders([]); }

    setLastFetch(new Date());
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 5000);
    return () => clearInterval(id);
  }, [fetchAll]);

  const availableCash = parseFloat(funds?.availablecash || 0);
  const usedMargin = parseFloat(funds?.utiliseddebits || 0);
  const totalBalance = availableCash + usedMargin;
  const utilPct = totalBalance > 0 ? (usedMargin / totalBalance) * 100 : 0;
  const totalPnl = positions.reduce((s, p) => s + parseFloat(p.pnl || 0), 0);

  return (
    <div className="space-y-6">
      {/* Market indices */}
      <div className="grid grid-cols-4 gap-4">
        {INDICES.map((idx) => (
          <IndexCard key={idx.symbol} data={indices[`${idx.exchange}:${idx.symbol}`]} name={idx.name} />
        ))}
      </div>

      {/* Account metrics */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
          <div className="flex items-center gap-2 text-xs text-gray-500 uppercase tracking-wide mb-3">
            <Wallet size={14} /> Available Balance
          </div>
          <div className="text-3xl font-bold font-mono text-emerald-400">
            {funds ? `₹${INR0.format(availableCash)}` : "—"}
          </div>
        </div>

        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
          <div className="flex items-center gap-2 text-xs text-gray-500 uppercase tracking-wide mb-3">
            <Activity size={14} /> Used Margin
          </div>
          <div className="text-3xl font-bold font-mono text-yellow-400">
            {funds ? `₹${INR0.format(usedMargin)}` : "—"}
          </div>
          <div className="w-full bg-gray-800 rounded-full h-1.5 mt-3">
            <div
              className={`h-1.5 rounded-full transition-all ${utilPct > 80 ? "bg-red-500" : utilPct > 50 ? "bg-yellow-500" : "bg-emerald-500"}`}
              style={{ width: `${Math.min(utilPct, 100)}%` }}
            />
          </div>
          <div className="text-xs text-gray-600 mt-1">{utilPct.toFixed(1)}% utilized</div>
        </div>

        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
          <div className="flex items-center gap-2 text-xs text-gray-500 uppercase tracking-wide mb-3">
            <TrendingUp size={14} /> Today's P&L
          </div>
          <div className={`text-3xl font-bold font-mono ${totalPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {totalPnl !== 0 ? `${totalPnl >= 0 ? "+" : ""}₹${INR0.format(Math.abs(totalPnl))}` : "₹0"}
          </div>
          <div className="text-xs text-gray-600 mt-1">{positions.length} position{positions.length !== 1 ? "s" : ""}</div>
        </div>

        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
          <div className="flex items-center gap-2 text-xs text-gray-500 uppercase tracking-wide mb-3">
            <ShoppingCart size={14} /> Orders
          </div>
          <div className="text-3xl font-bold font-mono">
            {orderStats ? orderStats.total_completed_orders : orders.length}
          </div>
          <div className="text-xs text-gray-600 mt-1">
            {orderStats
              ? `Open: ${orderStats.total_open_orders} · Rejected: ${orderStats.total_rejected_orders}`
              : "No orders today"}
          </div>
        </div>
      </div>

      {/* Positions table */}
      <div className="bg-gray-900 rounded-xl border border-gray-800">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800">
          <h3 className="text-sm text-gray-400 uppercase tracking-wide">Open Positions</h3>
          {lastFetch && (
            <div className="flex items-center gap-1.5 text-xs text-gray-600">
              <Clock size={10} />
              {lastFetch.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </div>
          )}
        </div>
        {positions.length === 0 ? (
          <div className="px-5 py-10 text-center text-gray-600 text-sm">No open positions</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-5 py-3 text-left">Symbol</th>
                <th className="px-5 py-3 text-center">Exchange</th>
                <th className="px-5 py-3 text-center">Product</th>
                <th className="px-5 py-3 text-right">Qty</th>
                <th className="px-5 py-3 text-right">Avg Price</th>
                <th className="px-5 py-3 text-right">LTP</th>
                <th className="px-5 py-3 text-right">P&L</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => {
                const pnl = parseFloat(p.pnl || 0);
                return (
                  <tr key={i} className="border-t border-gray-800/50 hover:bg-gray-800/30">
                    <td className="px-5 py-2.5 font-medium font-mono">{p.symbol}</td>
                    <td className="px-5 py-2.5 text-center text-gray-400">{p.exchange}</td>
                    <td className="px-5 py-2.5 text-center text-gray-400">{p.product}</td>
                    <td className="px-5 py-2.5 text-right font-mono">{p.quantity}</td>
                    <td className="px-5 py-2.5 text-right font-mono">{INR.format(p.average_price)}</td>
                    <td className="px-5 py-2.5 text-right font-mono">{INR.format(p.ltp)}</td>
                    <td className={`px-5 py-2.5 text-right font-mono font-semibold ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {pnl >= 0 ? "+" : ""}₹{INR0.format(Math.abs(pnl))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Recent orders */}
      <div className="bg-gray-900 rounded-xl border border-gray-800">
        <div className="px-5 py-3 border-b border-gray-800">
          <h3 className="text-sm text-gray-400 uppercase tracking-wide">Recent Orders</h3>
        </div>
        {orders.length === 0 ? (
          <div className="px-5 py-10 text-center text-gray-600 text-sm">No orders today</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-5 py-3 text-left">Time</th>
                <th className="px-5 py-3 text-left">Symbol</th>
                <th className="px-5 py-3 text-center">Action</th>
                <th className="px-5 py-3 text-right">Qty</th>
                <th className="px-5 py-3 text-right">Price</th>
                <th className="px-5 py-3 text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o, i) => (
                <tr key={i} className="border-t border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-5 py-2.5 text-gray-400 text-xs font-mono">{o.timestamp || "—"}</td>
                  <td className="px-5 py-2.5 font-medium font-mono">{o.symbol}</td>
                  <td className={`px-5 py-2.5 text-center font-semibold ${o.action === "BUY" ? "text-emerald-400" : "text-red-400"}`}>{o.action}</td>
                  <td className="px-5 py-2.5 text-right font-mono">{o.quantity}</td>
                  <td className="px-5 py-2.5 text-right font-mono">{o.price || "MKT"}</td>
                  <td className="px-5 py-2.5 text-center">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      o.order_status === "complete" ? "bg-emerald-500/10 text-emerald-400" :
                      o.order_status === "rejected" ? "bg-red-500/10 text-red-400" :
                      "bg-yellow-500/10 text-yellow-400"
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
