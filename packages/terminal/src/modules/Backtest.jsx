import { useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts";
import { Play, Download } from "lucide-react";

const STRATEGIES = ["EMACrossover", "Supertrend", "MACD_RSI", "BollingerMR", "VWAPDev", "StraddleSell", "MomentumBreakout", "ORB"];

function MetricCard({ label, value, color = "text-gray-100" }) {
  return (
    <div className="bg-gray-800 rounded-lg p-3">
      <div className="text-[10px] text-gray-600 mb-1">{label}</div>
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
  const [result, setResult] = useState(null);

  const runBacktest = () => {
    // Backtest engine backend not yet connected.
    // When ready, this will POST to the backtest-engine API.
    setRunning(true);
    setTimeout(() => {
      setRunning(false);
      setResult(null); // No mock results
    }, 500);
  };

  return (
    <div className="space-y-4">
      {/* Form */}
      <div className="flex items-end gap-3 flex-wrap bg-gray-900 p-4 rounded-xl border border-gray-800 text-xs">
        <div>
          <label className="block text-gray-500 mb-1">Strategy</label>
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)} className="bg-gray-800 rounded-lg px-2.5 py-1.5">
            {STRATEGIES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-gray-500 mb-1">Symbol</label>
          <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} className="bg-gray-800 rounded-lg px-2.5 py-1.5 w-24" />
        </div>
        <div>
          <label className="block text-gray-500 mb-1">Exchange</label>
          <select value={exchange} onChange={(e) => setExchange(e.target.value)} className="bg-gray-800 rounded-lg px-2.5 py-1.5">
            <option>NSE</option><option>NFO</option><option>MCX</option><option>CDS</option>
          </select>
        </div>
        <div>
          <label className="block text-gray-500 mb-1">Start</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="bg-gray-800 rounded-lg px-2.5 py-1.5" />
        </div>
        <div>
          <label className="block text-gray-500 mb-1">End</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="bg-gray-800 rounded-lg px-2.5 py-1.5" />
        </div>
        <div>
          <label className="block text-gray-500 mb-1">Capital</label>
          <input value={capital} onChange={(e) => setCapital(e.target.value)} className="bg-gray-800 rounded-lg px-2.5 py-1.5 w-28" />
        </div>
        <button onClick={runBacktest} disabled={running}
          className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white px-4 py-1.5 rounded-lg font-semibold transition-colors">
          <Play size={14} /> {running ? "Running..." : "Run Backtest"}
        </button>
      </div>

      {result ? (
        <>
          <div className="grid grid-cols-7 gap-2">
            <MetricCard label="Sharpe" value={result.sharpe} />
            <MetricCard label="Sortino" value={result.sortino} />
            <MetricCard label="Max DD" value={result.maxDD} color="text-red-400" />
            <MetricCard label="Win Rate" value={result.winRate} />
            <MetricCard label="Profit Factor" value={result.profitFactor} />
            <MetricCard label="Total Return" value={result.totalReturn} color="text-emerald-400" />
            <MetricCard label="CAGR" value={result.cagr} />
          </div>
        </>
      ) : (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-10 text-center">
          <FlaskIcon className="text-gray-700 mx-auto mb-3" />
          <p className="text-gray-500 text-sm">
            {running ? "Running backtest..." : "Configure parameters and run a backtest"}
          </p>
          <p className="text-gray-600 text-xs mt-1">
            Results will appear here with equity curve, drawdown, and trade log
          </p>
        </div>
      )}
    </div>
  );
}

function FlaskIcon({ className }) {
  return <FlaskConicalIcon size={32} className={className} />;
}

// Inline the icon to avoid import issues with the conditional render
function FlaskConicalIcon({ size, className }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2" />
      <path d="M8.5 2h7" />
      <path d="M7 16.5h10" />
    </svg>
  );
}
