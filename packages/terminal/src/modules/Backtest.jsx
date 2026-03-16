import { useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts";
import { Play, Download } from "lucide-react";

const STRATEGIES = ["EMACrossover", "Supertrend", "MACD_RSI", "BollingerMR", "VWAPDev", "StraddleSell", "MomentumBreakout", "ORB"];

function MetricCard({ label, value, color = "text-gray-100" }) {
  return (
    <div className="bg-gray-800 rounded-lg p-3">
      <div className="text-[10px] text-gray-500 mb-1">{label}</div>
      <div className={`text-sm font-bold font-mono ${color}`}>{value}</div>
    </div>
  );
}

export default function Backtest() {
  const [strategy, setStrategy] = useState("EMACrossover");
  const [symbol, setSymbol] = useState("RELIANCE");
  const [exchange, setExchange] = useState("NSE");
  const [startDate, setStartDate] = useState("2025-01-01");
  const [endDate, setEndDate] = useState("2025-12-31");
  const [capital, setCapital] = useState("1000000");
  const [running, setRunning] = useState(false);
  const [hasResult, setHasResult] = useState(false);

  // Sample result data
  const equity = Array.from({ length: 60 }, (_, i) => ({
    day: i + 1,
    equity: 1000000 + (Math.random() - 0.4) * 20000 + i * 800,
  }));
  const drawdown = equity.map((e, i) => ({ day: e.day, dd: -(Math.random() * 5) }));

  const trades = [
    { date: "2025-02-10", symbol: "RELIANCE", action: "BUY", qty: 10, entry: 2400, exit: 2520, pnl: 1200 },
    { date: "2025-03-05", symbol: "RELIANCE", action: "SELL", qty: 10, entry: 2520, exit: 2480, pnl: -400 },
    { date: "2025-04-12", symbol: "RELIANCE", action: "BUY", qty: 10, entry: 2500, exit: 2650, pnl: 1500 },
  ];

  const runBacktest = () => {
    setRunning(true);
    setTimeout(() => { setRunning(false); setHasResult(true); }, 1500);
  };

  return (
    <div className="space-y-4">
      {/* Form */}
      <div className="flex items-end gap-3 flex-wrap bg-gray-900 p-3 rounded-lg border border-gray-800 text-xs">
        <div>
          <label className="block text-gray-500 mb-1">Strategy</label>
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)} className="bg-gray-800 rounded px-2 py-1.5">
            {STRATEGIES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-gray-500 mb-1">Symbol</label>
          <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} className="bg-gray-800 rounded px-2 py-1.5 w-24" />
        </div>
        <div>
          <label className="block text-gray-500 mb-1">Exchange</label>
          <select value={exchange} onChange={(e) => setExchange(e.target.value)} className="bg-gray-800 rounded px-2 py-1.5">
            <option>NSE</option><option>NFO</option><option>MCX</option><option>CDS</option>
          </select>
        </div>
        <div>
          <label className="block text-gray-500 mb-1">Start</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="bg-gray-800 rounded px-2 py-1.5" />
        </div>
        <div>
          <label className="block text-gray-500 mb-1">End</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="bg-gray-800 rounded px-2 py-1.5" />
        </div>
        <div>
          <label className="block text-gray-500 mb-1">Capital</label>
          <input value={capital} onChange={(e) => setCapital(e.target.value)} className="bg-gray-800 rounded px-2 py-1.5 w-28" />
        </div>
        <button onClick={runBacktest} disabled={running}
          className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white px-4 py-1.5 rounded font-semibold">
          <Play size={14} /> {running ? "Running..." : "Run Backtest"}
        </button>
      </div>

      {hasResult && (
        <>
          {/* Metrics */}
          <div className="grid grid-cols-7 gap-2">
            <MetricCard label="Sharpe" value="1.85" />
            <MetricCard label="Sortino" value="2.41" />
            <MetricCard label="Max DD" value="-8.2%" color="text-red-400" />
            <MetricCard label="Win Rate" value="62%" />
            <MetricCard label="Profit Factor" value="1.9" />
            <MetricCard label="Total Return" value="+24.5%" color="text-emerald-400" />
            <MetricCard label="CAGR" value="24.5%" />
          </div>

          {/* Charts */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
              <div className="text-xs text-gray-400 mb-2">Equity Curve</div>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={equity}>
                  <defs><linearGradient id="ecGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} /><stop offset="95%" stopColor="#22c55e" stopOpacity={0} /></linearGradient></defs>
                  <XAxis dataKey="day" tick={{ fill: "#6b7280", fontSize: 9 }} />
                  <YAxis tick={{ fill: "#6b7280", fontSize: 9 }} domain={["auto", "auto"]} />
                  <Tooltip contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8, fontSize: 11 }} />
                  <Area type="monotone" dataKey="equity" stroke="#22c55e" fill="url(#ecGrad)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
              <div className="text-xs text-gray-400 mb-2">Drawdown</div>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={drawdown}>
                  <XAxis dataKey="day" tick={{ fill: "#6b7280", fontSize: 9 }} />
                  <YAxis tick={{ fill: "#6b7280", fontSize: 9 }} />
                  <Tooltip contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8, fontSize: 11 }} />
                  <Area type="monotone" dataKey="dd" stroke="#ef4444" fill="rgba(239,68,68,0.15)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Trade log */}
          <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-800">
                <tr className="text-gray-400">
                  <th className="px-3 py-2 text-left">Date</th><th className="px-3 py-2 text-left">Symbol</th>
                  <th className="px-3 py-2">Action</th><th className="px-3 py-2 text-right">Qty</th>
                  <th className="px-3 py-2 text-right">Entry</th><th className="px-3 py-2 text-right">Exit</th>
                  <th className="px-3 py-2 text-right">P&L</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={i} className="border-t border-gray-800 hover:bg-gray-800/30">
                    <td className="px-3 py-1.5">{t.date}</td><td className="px-3 py-1.5">{t.symbol}</td>
                    <td className={`px-3 py-1.5 text-center ${t.action === "BUY" ? "text-emerald-400" : "text-red-400"}`}>{t.action}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{t.qty}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{t.entry}</td>
                    <td className="px-3 py-1.5 text-right font-mono">{t.exit}</td>
                    <td className={`px-3 py-1.5 text-right font-mono ${t.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>{t.pnl >= 0 ? "+" : ""}{t.pnl}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
