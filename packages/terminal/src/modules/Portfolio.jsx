import { useState, useEffect } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { Download, RefreshCw } from "lucide-react";
import { getPositionbook, getOrderbook, getTradebook, getHoldings, getFunds } from "../services/api";

const TABS = ["Positions", "Orders", "Trades", "Holdings", "Funds"];
const COLORS = ["#22c55e", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"];

function fmtINR(v) {
  return Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

export default function Portfolio() {
  const [tab, setTab] = useState(0);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [trades, setTrades] = useState([]);
  const [holdings, setHoldings] = useState([]);
  const [funds, setFunds] = useState({});
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const [p, o, t, h, f] = await Promise.allSettled([
        getPositionbook(), getOrderbook(), getTradebook(), getHoldings(), getFunds(),
      ]);
      if (p.status === "fulfilled" && Array.isArray(p.value)) setPositions(p.value);
      if (o.status === "fulfilled") {
        const ob = o.value;
        setOrders(ob?.orders || (Array.isArray(ob) ? ob : []));
      }
      if (t.status === "fulfilled") {
        const tb = t.value;
        setTrades(tb?.trades || (Array.isArray(tb) ? tb : []));
      }
      if (h.status === "fulfilled" && Array.isArray(h.value)) setHoldings(h.value);
      if (f.status === "fulfilled") setFunds(f.value);
    } catch { /* */ }
    setLoading(false);
  };

  useEffect(() => { refresh(); }, []);

  const exportCSV = () => {
    const rows = trades.map((t) => `${t.timestamp || ""},${t.symbol},${t.exchange},${t.action},${t.quantity},${t.price}`);
    const csv = "Timestamp,Symbol,Exchange,Action,Qty,Price\n" + rows.join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "trades.csv";
    a.click();
  };

  const holdingSectors = holdings.reduce((acc, h) => {
    const sec = h.exchange || "NSE";
    acc[sec] = (acc[sec] || 0) + Math.abs(parseFloat(h.pnl || 0));
    return acc;
  }, {});
  const sectorData = Object.entries(holdingSectors).map(([name, value]) => ({ name, value: Math.max(value, 1) }));

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Tab bar */}
      <div className="flex items-center gap-1 bg-gray-900 p-1 rounded-lg border border-gray-800">
        {TABS.map((t, i) => (
          <button key={t} onClick={() => setTab(i)}
            className={`px-3 py-1.5 text-xs rounded ${tab === i ? "bg-gray-800 text-gray-100" : "text-gray-400 hover:text-gray-200"}`}>
            {t}
          </button>
        ))}
        <div className="ml-auto flex gap-1">
          {tab === 2 && <button onClick={exportCSV} className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-200 px-2 py-1"><Download size={12} /> CSV</button>}
          <button onClick={refresh} className={`text-gray-400 hover:text-gray-200 p-1 ${loading ? "animate-spin" : ""}`}><RefreshCw size={14} /></button>
        </div>
      </div>

      {/* Positions */}
      {tab === 0 && (
        <div className="flex-1 overflow-auto bg-gray-900 rounded-lg border border-gray-800">
          <table className="w-full text-xs">
            <thead className="bg-gray-800 sticky top-0"><tr className="text-gray-400">
              <th className="px-3 py-2 text-left">Symbol</th><th className="px-3 py-2">Exchange</th><th className="px-3 py-2">Product</th>
              <th className="px-3 py-2 text-right">Qty</th><th className="px-3 py-2 text-right">Avg Price</th>
              <th className="px-3 py-2 text-right">LTP</th><th className="px-3 py-2 text-right">P&L</th>
            </tr></thead>
            <tbody>
              {positions.map((p, i) => {
                const pnl = parseFloat(p.pnl || 0);
                return (
                  <tr key={i} className="border-t border-gray-800/50 hover:bg-gray-800/30">
                    <td className="px-3 py-1.5 font-medium">{p.symbol}</td>
                    <td className="px-3 py-1.5 text-center">{p.exchange}</td>
                    <td className="px-3 py-1.5 text-center">{p.product}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{p.quantity}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{p.average_price}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{p.ltp}</td>
                    <td className={`px-3 py-1.5 text-right font-mono font-semibold ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmtINR(pnl)}</td>
                  </tr>
                );
              })}
              {positions.length === 0 && <tr><td colSpan={7} className="px-3 py-6 text-center text-gray-500">No open positions</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {/* Orders */}
      {tab === 1 && (
        <div className="flex-1 overflow-auto bg-gray-900 rounded-lg border border-gray-800">
          <table className="w-full text-xs">
            <thead className="bg-gray-800 sticky top-0"><tr className="text-gray-400">
              <th className="px-3 py-2 text-left">Order ID</th><th className="px-3 py-2">Symbol</th><th className="px-3 py-2">Action</th>
              <th className="px-3 py-2 text-right">Qty</th><th className="px-3 py-2 text-right">Price</th><th className="px-3 py-2">Status</th>
            </tr></thead>
            <tbody>
              {orders.map((o, i) => (
                <tr key={i} className="border-t border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-3 py-1.5 font-mono text-xs">{o.orderid}</td>
                  <td className="px-3 py-1.5">{o.symbol}</td>
                  <td className={`px-3 py-1.5 text-center ${o.action === "BUY" ? "text-emerald-400" : "text-red-400"}`}>{o.action}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{o.quantity}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{o.price}</td>
                  <td className="px-3 py-1.5 text-center"><span className="px-1.5 py-0.5 rounded text-[10px] bg-gray-800">{o.status}</span></td>
                </tr>
              ))}
              {orders.length === 0 && <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-500">No orders</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {/* Trades */}
      {tab === 2 && (
        <div className="flex-1 overflow-auto bg-gray-900 rounded-lg border border-gray-800">
          <table className="w-full text-xs">
            <thead className="bg-gray-800 sticky top-0"><tr className="text-gray-400">
              <th className="px-3 py-2 text-left">Time</th><th className="px-3 py-2">Symbol</th><th className="px-3 py-2">Action</th>
              <th className="px-3 py-2 text-right">Qty</th><th className="px-3 py-2 text-right">Price</th>
            </tr></thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={i} className="border-t border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-3 py-1.5 text-gray-400">{t.timestamp}</td>
                  <td className="px-3 py-1.5">{t.symbol}</td>
                  <td className={`px-3 py-1.5 text-center ${t.action === "BUY" ? "text-emerald-400" : "text-red-400"}`}>{t.action}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{t.quantity}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{t.price}</td>
                </tr>
              ))}
              {trades.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-500">No trades today</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {/* Holdings */}
      {tab === 3 && (
        <div className="grid grid-cols-3 gap-3 flex-1">
          <div className="col-span-2 overflow-auto bg-gray-900 rounded-lg border border-gray-800">
            <table className="w-full text-xs">
              <thead className="bg-gray-800 sticky top-0"><tr className="text-gray-400">
                <th className="px-3 py-2 text-left">Symbol</th><th className="px-3 py-2 text-right">Qty</th>
                <th className="px-3 py-2 text-right">Avg</th><th className="px-3 py-2 text-right">LTP</th>
                <th className="px-3 py-2 text-right">P&L</th><th className="px-3 py-2 text-right">P&L%</th>
              </tr></thead>
              <tbody>
                {holdings.map((h, i) => {
                  const pnl = parseFloat(h.pnl || 0);
                  return (
                    <tr key={i} className="border-t border-gray-800/50 hover:bg-gray-800/30">
                      <td className="px-3 py-1.5 font-medium">{h.symbol}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{h.quantity}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{h.average_price}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{h.ltp}</td>
                      <td className={`px-3 py-1.5 text-right font-mono ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>{fmtINR(pnl)}</td>
                      <td className={`px-3 py-1.5 text-right font-mono ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>{h.pnl_percent || 0}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-3 flex flex-col items-center justify-center">
            <div className="text-xs text-gray-400 mb-2">Allocation</div>
            {sectorData.length > 0 ? (
              <ResponsiveContainer width="100%" height={180}>
                <PieChart><Pie data={sectorData} cx="50%" cy="50%" innerRadius={40} outerRadius={70} dataKey="value" paddingAngle={2}>
                  {sectorData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie><Tooltip contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8, fontSize: 11 }} /></PieChart>
              </ResponsiveContainer>
            ) : <div className="text-gray-500 text-xs">No holdings data</div>}
          </div>
        </div>
      )}

      {/* Funds */}
      {tab === 4 && (
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Available Cash</div>
            <div className="text-xl font-bold font-mono text-emerald-400">₹{fmtINR(funds.availablecash)}</div>
          </div>
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Used Margin</div>
            <div className="text-xl font-bold font-mono text-yellow-400">₹{fmtINR(funds.utiliseddebits)}</div>
          </div>
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Collateral</div>
            <div className="text-xl font-bold font-mono">₹{fmtINR(funds.collateral)}</div>
          </div>
        </div>
      )}
    </div>
  );
}
