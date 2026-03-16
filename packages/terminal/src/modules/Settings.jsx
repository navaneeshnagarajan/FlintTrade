import { useState, useEffect } from "react";
import { Wifi, WifiOff, Shield, ShieldOff, Keyboard, Save, Sun, Moon } from "lucide-react";
import { ping, analyzerStatus, analyzerToggle } from "../services/api";

const SHORTCUTS = [
  ["F1", "Dashboard"], ["F2", "Scalper"], ["F3", "Option Chain"], ["F4", "Futures OI"],
  ["F5", "Strategy"], ["F6", "Backtest"], ["F7", "Portfolio"], ["F8", "Journal"], ["F9", "Settings"],
  ["B / ↑", "Quick Buy"], ["S / ↓", "Quick Sell"], ["X", "Exit All"], ["C", "Cancel All"],
  ["Space", "Toggle SL Trail"], ["Ctrl+K", "Command Palette"], ["Enter", "Confirm Order"], ["Esc", "Close Modal"],
  ["1-9", "Strike Offset"], ["Tab", "Switch Panel"],
];

export default function Settings() {
  const [host, setHost] = useState(import.meta.env.VITE_OPENALGO_HOST || "http://127.0.0.1:5000");
  const [apiKey, setApiKey] = useState(import.meta.env.VITE_OPENALGO_API_KEY || "");
  const [connected, setConnected] = useState(false);
  const [sandbox, setSandbox] = useState(false);
  const [checking, setChecking] = useState(false);

  const [defaultProduct, setDefaultProduct] = useState("MIS");
  const [defaultOrderType, setDefaultOrderType] = useState("MARKET");
  const [defaultQty, setDefaultQty] = useState("75");
  const [maxOrderSize, setMaxOrderSize] = useState("5000");
  const [dailyLossLimit, setDailyLossLimit] = useState("50000");
  const [maxPositions, setMaxPositions] = useState("10");
  const [darkMode, setDarkMode] = useState(true);

  const checkConnection = async () => {
    setChecking(true);
    try {
      await ping();
      setConnected(true);
      const status = await analyzerStatus();
      setSandbox(status?.analyzer === true || status?.status === "active");
    } catch {
      setConnected(false);
    }
    setChecking(false);
  };

  useEffect(() => { checkConnection(); }, []);

  const toggleSandbox = async () => {
    try {
      await analyzerToggle();
      setSandbox((v) => !v);
    } catch { /* */ }
  };

  return (
    <div className="max-w-3xl space-y-6">
      {/* Connection */}
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-4 space-y-3">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          {connected ? <Wifi size={16} className="text-emerald-400" /> : <WifiOff size={16} className="text-red-400" />}
          OpenAlgo Connection
        </h2>
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="block text-xs text-gray-400 mb-1">Host URL</label>
            <input value={host} onChange={(e) => setHost(e.target.value)} className="w-full bg-gray-800 rounded px-3 py-2 text-sm" />
          </div>
          <div className="flex-1">
            <label className="block text-xs text-gray-400 mb-1">API Key</label>
            <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} type="password" className="w-full bg-gray-800 rounded px-3 py-2 text-sm" />
          </div>
          <button onClick={checkConnection} disabled={checking}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm px-4 py-2 rounded font-semibold shrink-0">
            {checking ? "Checking..." : connected ? "Connected" : "Connect"}
          </button>
        </div>
        <div className={`text-xs ${connected ? "text-emerald-400" : "text-red-400"}`}>
          {connected ? "Connected to OpenAlgo" : "Not connected"}
        </div>
      </section>

      {/* Sandbox toggle */}
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold flex items-center gap-2">
              {sandbox ? <Shield size={16} className="text-orange-400" /> : <ShieldOff size={16} className="text-gray-400" />}
              Sandbox Mode (Analyzer)
            </h2>
            <p className="text-xs text-gray-500 mt-1">When ON, orders go through OpenAlgo's analyzer — not real broker.</p>
          </div>
          <button onClick={toggleSandbox}
            className={`px-4 py-1.5 rounded text-sm font-semibold ${sandbox ? "bg-orange-500 text-white" : "bg-gray-700 text-gray-300 hover:bg-gray-600"}`}>
            {sandbox ? "Sandbox ON" : "Go Sandbox"}
          </button>
        </div>
      </section>

      {/* Trading preferences */}
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-4 space-y-3">
        <h2 className="text-sm font-semibold">Trading Preferences</h2>
        <div className="grid grid-cols-3 gap-3 text-xs">
          <div>
            <label className="block text-gray-400 mb-1">Default Product</label>
            <select value={defaultProduct} onChange={(e) => setDefaultProduct(e.target.value)} className="w-full bg-gray-800 rounded px-2 py-1.5">
              <option>MIS</option><option>CNC</option><option>NRML</option>
            </select>
          </div>
          <div>
            <label className="block text-gray-400 mb-1">Default Order Type</label>
            <select value={defaultOrderType} onChange={(e) => setDefaultOrderType(e.target.value)} className="w-full bg-gray-800 rounded px-2 py-1.5">
              <option>MARKET</option><option>LIMIT</option>
            </select>
          </div>
          <div>
            <label className="block text-gray-400 mb-1">Default Qty</label>
            <input value={defaultQty} onChange={(e) => setDefaultQty(e.target.value)} className="w-full bg-gray-800 rounded px-2 py-1.5" />
          </div>
        </div>
      </section>

      {/* Risk limits */}
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-4 space-y-3">
        <h2 className="text-sm font-semibold">Risk Limits</h2>
        <div className="grid grid-cols-3 gap-3 text-xs">
          <div>
            <label className="block text-gray-400 mb-1">Max Order Size</label>
            <input value={maxOrderSize} onChange={(e) => setMaxOrderSize(e.target.value)} className="w-full bg-gray-800 rounded px-2 py-1.5" />
          </div>
          <div>
            <label className="block text-gray-400 mb-1">Daily Loss Limit</label>
            <input value={dailyLossLimit} onChange={(e) => setDailyLossLimit(e.target.value)} className="w-full bg-gray-800 rounded px-2 py-1.5" />
          </div>
          <div>
            <label className="block text-gray-400 mb-1">Max Positions</label>
            <input value={maxPositions} onChange={(e) => setMaxPositions(e.target.value)} className="w-full bg-gray-800 rounded px-2 py-1.5" />
          </div>
        </div>
      </section>

      {/* Keyboard shortcuts */}
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <h2 className="text-sm font-semibold flex items-center gap-2 mb-3"><Keyboard size={16} /> Keyboard Shortcuts</h2>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
          {SHORTCUTS.map(([key, action]) => (
            <div key={key} className="flex justify-between py-1 border-b border-gray-800/50">
              <kbd className="bg-gray-800 px-1.5 py-0.5 rounded font-mono text-gray-300">{key}</kbd>
              <span className="text-gray-400">{action}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
