import { useState, useEffect, useRef } from "react";
import { Play, Loader2 } from "lucide-react";
import { searchSymbol } from "../services/api";
import ParamInput from "../components/ParamInput";

const STRATEGIES = [
  {
    id: "EMACrossover", label: "EMA Crossover",
    params: [
      { name: "fast_period", label: "Fast EMA Period", type: "number", default: 9, min: 2, max: 200 },
      { name: "slow_period", label: "Slow EMA Period", type: "number", default: 21, min: 2, max: 200 },
    ],
  },
  {
    id: "Supertrend", label: "Supertrend",
    params: [
      { name: "period", label: "ATR Period", type: "number", default: 10, min: 1, max: 100 },
      { name: "multiplier", label: "Multiplier", type: "number", default: 3.0, min: 0.5, max: 10, step: 0.1 },
    ],
  },
  {
    id: "MACD_RSI", label: "MACD + RSI",
    params: [
      { name: "macd_fast", label: "MACD Fast", type: "number", default: 12, min: 2, max: 100 },
      { name: "macd_slow", label: "MACD Slow", type: "number", default: 26, min: 2, max: 200 },
      { name: "macd_signal", label: "MACD Signal", type: "number", default: 9, min: 2, max: 50 },
      { name: "rsi_period", label: "RSI Period", type: "number", default: 14, min: 2, max: 50 },
      { name: "rsi_oversold", label: "RSI Oversold", type: "number", default: 30, min: 5, max: 50 },
      { name: "rsi_overbought", label: "RSI Overbought", type: "number", default: 70, min: 50, max: 95 },
    ],
  },
  {
    id: "BollingerMR", label: "Bollinger Mean Reversion",
    params: [
      { name: "period", label: "BB Period", type: "number", default: 20, min: 5, max: 100 },
      { name: "std_mult", label: "Std Multiplier", type: "number", default: 2.0, min: 0.5, max: 5, step: 0.1 },
    ],
  },
  {
    id: "VWAPDev", label: "VWAP Deviation",
    params: [
      { name: "deviation_pct", label: "Deviation %", type: "number", default: 1.0, min: 0.1, max: 5, step: 0.1 },
    ],
  },
  {
    id: "StraddleSell", label: "Straddle Sell",
    params: [
      { name: "entry_time", label: "Entry Time", type: "select", default: "09:20", options: ["09:16", "09:20", "09:30", "09:45", "10:00"] },
      { name: "exit_time", label: "Exit Time", type: "select", default: "15:15", options: ["14:30", "15:00", "15:15", "15:25"] },
      { name: "stop_loss_pct", label: "Stop Loss %", type: "number", default: 30, min: 5, max: 100 },
    ],
  },
  {
    id: "StrangleSell", label: "Strangle Sell",
    params: [
      { name: "entry_time", label: "Entry Time", type: "select", default: "09:20", options: ["09:16", "09:20", "09:30", "09:45", "10:00"] },
      { name: "exit_time", label: "Exit Time", type: "select", default: "15:15", options: ["14:30", "15:00", "15:15", "15:25"] },
      { name: "stop_loss_pct", label: "Stop Loss %", type: "number", default: 30, min: 5, max: 100 },
      { name: "delta", label: "Delta", type: "number", default: 0.3, min: 0.05, max: 0.5, step: 0.05 },
    ],
  },
  {
    id: "IronCondor", label: "Iron Condor",
    params: [
      { name: "entry_time", label: "Entry Time", type: "select", default: "09:20", options: ["09:16", "09:20", "09:30", "09:45", "10:00"] },
      { name: "exit_time", label: "Exit Time", type: "select", default: "15:15", options: ["14:30", "15:00", "15:15", "15:25"] },
      { name: "stop_loss_pct", label: "Stop Loss %", type: "number", default: 30, min: 5, max: 100 },
      { name: "wing_width", label: "Wing Width (pts)", type: "number", default: 100, min: 25, max: 500, step: 25 },
    ],
  },
  {
    id: "BullPutSpread", label: "Bull Put Spread",
    params: [
      { name: "entry_time", label: "Entry Time", type: "select", default: "09:20", options: ["09:16", "09:20", "09:30", "09:45", "10:00"] },
      { name: "exit_time", label: "Exit Time", type: "select", default: "15:15", options: ["14:30", "15:00", "15:15", "15:25"] },
      { name: "stop_loss_pct", label: "Stop Loss %", type: "number", default: 30, min: 5, max: 100 },
      { name: "spread_width", label: "Spread Width (pts)", type: "number", default: 100, min: 25, max: 500, step: 25 },
    ],
  },
  {
    id: "BearCallSpread", label: "Bear Call Spread",
    params: [
      { name: "entry_time", label: "Entry Time", type: "select", default: "09:20", options: ["09:16", "09:20", "09:30", "09:45", "10:00"] },
      { name: "exit_time", label: "Exit Time", type: "select", default: "15:15", options: ["14:30", "15:00", "15:15", "15:25"] },
      { name: "stop_loss_pct", label: "Stop Loss %", type: "number", default: 30, min: 5, max: 100 },
      { name: "spread_width", label: "Spread Width (pts)", type: "number", default: 100, min: 25, max: 500, step: 25 },
    ],
  },
  {
    id: "MomentumBreakout", label: "Momentum Breakout",
    params: [
      { name: "lookback", label: "Lookback Bars", type: "number", default: 20, min: 5, max: 100 },
      { name: "volume_mult", label: "Volume Multiplier", type: "number", default: 1.5, min: 1.0, max: 5, step: 0.1 },
    ],
  },
  {
    id: "ORB", label: "Opening Range Breakout",
    params: [
      { name: "range_minutes", label: "Range Minutes", type: "number", default: 15, min: 5, max: 60, step: 5 },
      { name: "exit_time", label: "Exit Time", type: "select", default: "15:15", options: ["14:30", "15:00", "15:15", "15:25"] },
    ],
  },
];

const EXCHANGES = ["NSE", "NFO", "BFO", "CDS", "MCX", "BSE"];
const TIMEFRAMES = ["1m", "3m", "5m", "15m", "1h", "1D"];
const SIZING_MODES = ["Fixed Qty", "Fixed Amount", "% of Capital", "Kelly Criterion"];
const COMMISSION_MODES = ["Flat per Order", "% of Turnover", "Zerodha", "Angel One", "None"];
const SLIPPAGE_MODES = ["Fixed Points", "% of Price", "None"];

export default function ConfigPanel({ onRun, running }) {
  const [strategy, setStrategy] = useState("EMACrossover");
  const [strategyParams, setStrategyParams] = useState({});
  const [symbol, setSymbol] = useState("RELIANCE");
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [exchange, setExchange] = useState("NSE");
  const [startDate, setStartDate] = useState("2025-01-01");
  const [endDate, setEndDate] = useState("2025-12-31");
  const [timeframe, setTimeframe] = useState("5m");
  const [capital, setCapital] = useState(100000);
  const [sizingMode, setSizingMode] = useState("% of Capital");
  const [sizingValue, setSizingValue] = useState(10);
  const [commissionMode, setCommissionMode] = useState("Flat per Order");
  const [commissionValue, setCommissionValue] = useState(20);
  const [slippageMode, setSlippageMode] = useState("% of Price");
  const [slippageValue, setSlippageValue] = useState(0.05);
  const [product, setProduct] = useState("MIS");
  const searchTimer = useRef(null);

  const selectedStrategy = STRATEGIES.find((s) => s.id === strategy);

  // Reset params when strategy changes
  useEffect(() => {
    if (!selectedStrategy) return;
    const defaults = {};
    for (const p of selectedStrategy.params) {
      defaults[p.name] = p.default;
    }
    setStrategyParams(defaults);
  }, [strategy]);

  const handleSymbolChange = (val) => {
    setSymbol(val.toUpperCase());
    clearTimeout(searchTimer.current);
    if (val.length < 2) { setSuggestions([]); setShowSuggestions(false); return; }
    searchTimer.current = setTimeout(async () => {
      try {
        const res = await searchSymbol(val);
        const list = res?.data || res?.results || [];
        setSuggestions(Array.isArray(list) ? list.slice(0, 8) : []);
        setShowSuggestions(true);
      } catch {
        setSuggestions([]);
      }
    }, 300);
  };

  const handleRun = () => {
    onRun({
      strategy,
      strategy_params: strategyParams,
      symbol,
      exchange,
      start_date: startDate,
      end_date: endDate,
      interval: timeframe,
      initial_capital: capital,
      sizing_mode: sizingMode,
      sizing_value: sizingValue,
      commission_mode: commissionMode,
      commission_value: commissionValue,
      slippage_mode: slippageMode,
      slippage_value: slippageValue,
      product,
    });
  };

  return (
    <div className="space-y-4 overflow-y-auto pr-1">
      {/* Strategy */}
      <section>
        <label className="block text-[10px] text-gray-500 mb-1 font-semibold uppercase tracking-wide">Strategy</label>
        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
          className="w-full bg-gray-800 rounded px-2 py-2 text-sm">
          {STRATEGIES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
      </section>

      {/* Strategy params */}
      {selectedStrategy && selectedStrategy.params.length > 0 && (
        <section className="bg-gray-900/50 rounded-lg border border-gray-800 p-3 space-y-2">
          <div className="text-[10px] text-gray-500 font-semibold uppercase tracking-wide mb-1">Strategy Parameters</div>
          <div className="grid grid-cols-2 gap-2">
            {selectedStrategy.params.map((p) => (
              <ParamInput
                key={p.name}
                param={p}
                value={strategyParams[p.name]}
                onChange={(v) => setStrategyParams((prev) => ({ ...prev, [p.name]: v }))}
              />
            ))}
          </div>
        </section>
      )}

      {/* Symbol + Exchange */}
      <section className="grid grid-cols-2 gap-2">
        <div className="relative">
          <label className="block text-[10px] text-gray-500 mb-1">Symbol</label>
          <input value={symbol}
            onChange={(e) => handleSymbolChange(e.target.value)}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs font-mono" />
          {showSuggestions && suggestions.length > 0 && (
            <div className="absolute z-20 top-full left-0 w-full bg-gray-800 border border-gray-700 rounded-b mt-0.5 max-h-40 overflow-y-auto">
              {suggestions.map((s, i) => (
                <button key={i} className="w-full text-left px-2 py-1 text-xs hover:bg-gray-700"
                  onMouseDown={() => { setSymbol(s.symbol || s); setShowSuggestions(false); }}>
                  {s.symbol || s} <span className="text-gray-500">{s.exchange || ""}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">Exchange</label>
          <select value={exchange} onChange={(e) => setExchange(e.target.value)}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs">
            {EXCHANGES.map((e) => <option key={e}>{e}</option>)}
          </select>
        </div>
      </section>

      {/* Date range */}
      <section className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">Start Date</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs" />
        </div>
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">End Date</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs" />
        </div>
      </section>

      {/* Timeframe + Capital */}
      <section className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">Timeframe</label>
          <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs">
            {TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">Initial Capital (₹)</label>
          <input type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))}
            min={1000} step={10000}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs font-mono" />
        </div>
      </section>

      {/* Position sizing */}
      <section className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">Position Sizing</label>
          <select value={sizingMode} onChange={(e) => setSizingMode(e.target.value)}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs">
            {SIZING_MODES.map((m) => <option key={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">
            {sizingMode === "Fixed Qty" ? "Qty" : sizingMode === "Fixed Amount" ? "Amount (₹)" : sizingMode === "% of Capital" ? "%" : "Fraction"}
          </label>
          <input type="number" value={sizingValue}
            onChange={(e) => setSizingValue(Number(e.target.value))}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs font-mono" />
        </div>
      </section>

      {/* Commission */}
      <section className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">Commission</label>
          <select value={commissionMode} onChange={(e) => setCommissionMode(e.target.value)}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs">
            {COMMISSION_MODES.map((m) => <option key={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">
            {commissionMode === "Flat per Order" ? "₹/order" : commissionMode === "% of Turnover" ? "%" : "—"}
          </label>
          <input type="number" value={commissionValue}
            onChange={(e) => setCommissionValue(Number(e.target.value))}
            disabled={commissionMode === "None"}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs font-mono disabled:opacity-50" />
        </div>
      </section>

      {/* Slippage + Product */}
      <section className="grid grid-cols-3 gap-2">
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">Slippage</label>
          <select value={slippageMode} onChange={(e) => setSlippageMode(e.target.value)}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs">
            {SLIPPAGE_MODES.map((m) => <option key={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">
            {slippageMode === "Fixed Points" ? "Points" : slippageMode === "% of Price" ? "%" : "—"}
          </label>
          <input type="number" value={slippageValue}
            onChange={(e) => setSlippageValue(Number(e.target.value))}
            step={0.01} disabled={slippageMode === "None"}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs font-mono disabled:opacity-50" />
        </div>
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">Product</label>
          <select value={product} onChange={(e) => setProduct(e.target.value)}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs">
            <option>MIS</option>
            <option>NRML</option>
          </select>
        </div>
      </section>

      {/* Run button */}
      <button onClick={handleRun} disabled={running}
        className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white py-3 rounded-lg font-semibold text-sm transition-colors">
        {running ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
        {running ? "Running Backtest..." : "Run Backtest"}
      </button>
    </div>
  );
}
