import { useState, useEffect, useMemo, useCallback } from "react";
import {
  LayoutDashboard, Crosshair, Table2, BarChart3, Puzzle,
  FlaskConical, Briefcase, BookOpen, Settings as SettingsIcon,
  Search, Shield, Clock,
} from "lucide-react";
import useKeyboard from "./hooks/useKeyboard";
import { ping } from "./services/api";

import Dashboard from "./modules/Dashboard";
import Scalper from "./modules/Scalper";
import OptionChain from "./modules/OptionChain";
import FuturesOI from "./modules/FuturesOI";
import Strategy from "./modules/Strategy";
import Backtest from "./modules/Backtest";
import Portfolio from "./modules/Portfolio";
import Journal from "./modules/Journal";
import Settings from "./modules/Settings";

const MODULES = [
  { name: "Dashboard", icon: LayoutDashboard, key: "F1", component: Dashboard },
  { name: "Scalper", icon: Crosshair, key: "F2", component: Scalper },
  { name: "Option Chain", icon: Table2, key: "F3", component: OptionChain },
  { name: "Futures OI", icon: BarChart3, key: "F4", component: FuturesOI },
  { name: "Strategy", icon: Puzzle, key: "F5", component: Strategy },
  { name: "Backtest", icon: FlaskConical, key: "F6", component: Backtest },
  { name: "Portfolio", icon: Briefcase, key: "F7", component: Portfolio },
  { name: "Journal", icon: BookOpen, key: "F8", component: Journal },
  { name: "Settings", icon: SettingsIcon, key: "F9", component: Settings },
];

function isMarketOpen() {
  const now = new Date();
  const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const h = ist.getHours();
  const m = ist.getMinutes();
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  const mins = h * 60 + m;
  return mins >= 555 && mins <= 930; // 9:15 - 15:30
}

function ISTClock() {
  const [time, setTime] = useState("");
  useEffect(() => {
    const tick = () => setTime(new Date().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return <span className="text-xs text-gray-500 font-mono">{time} IST</span>;
}

export default function App() {
  const [activeModule, setActiveModule] = useState(0);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [cmdQuery, setCmdQuery] = useState("");
  const [sandbox, setSandbox] = useState(false);
  const [apiConnected, setApiConnected] = useState(false);
  const [broker, setBroker] = useState("");
  const [marketOpen, setMarketOpen] = useState(isMarketOpen);

  // Ping OpenAlgo every 10 seconds
  useEffect(() => {
    const check = async () => {
      try {
        const data = await ping();
        setApiConnected(true);
        setBroker(data?.broker || "");
      } catch {
        setApiConnected(false);
        setBroker("");
      }
      setMarketOpen(isMarketOpen());
    };
    check();
    const id = setInterval(check, 10000);
    return () => clearInterval(id);
  }, []);

  const keyHandlers = useMemo(() => ({
    onCommandPalette: () => { setCmdOpen((v) => !v); setCmdQuery(""); },
    onEscape: () => setCmdOpen(false),
  }), []);

  useKeyboard(setActiveModule, keyHandlers);

  const ActiveComponent = MODULES[activeModule].component;

  const filteredModules = MODULES.filter((m) =>
    m.name.toLowerCase().includes(cmdQuery.toLowerCase())
  );

  return (
    <div className={`flex h-screen bg-gray-950 text-gray-100 ${sandbox ? "ring-2 ring-orange-500 ring-inset" : ""}`}>
      {/* Sidebar — 60px, icons only */}
      <aside className="flex flex-col items-center py-4 bg-gray-950 border-r border-gray-800 w-15 shrink-0">
        <div className="mb-6 text-emerald-400 font-bold text-lg">F</div>
        {MODULES.map((mod, i) => {
          const Icon = mod.icon;
          const active = activeModule === i;
          return (
            <button
              key={mod.name}
              onClick={() => setActiveModule(i)}
              title={`${mod.name} (${mod.key})`}
              className={`flex items-center justify-center w-10 h-10 mb-1 rounded-lg transition-colors ${
                active ? "bg-gray-800 text-white" : "text-gray-500 hover:text-gray-300 hover:bg-gray-800/50"
              }`}
            >
              <Icon size={20} />
            </button>
          );
        })}
      </aside>

      {/* Main area */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Top bar */}
        <header className="flex items-center justify-between px-6 py-2.5 bg-gray-900 border-b border-gray-800 shrink-0">
          <div className="flex items-center gap-3">
            <span className="font-semibold text-sm">{MODULES[activeModule].name}</span>
            <kbd className="text-[10px] text-gray-600 bg-gray-800 px-1.5 py-0.5 rounded">{MODULES[activeModule].key}</kbd>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => { setCmdOpen(true); setCmdQuery(""); }}
              className="flex items-center gap-1.5 text-xs text-gray-500 bg-gray-800 rounded-lg px-3 py-1.5 hover:bg-gray-700 hover:text-gray-300 transition-colors"
            >
              <Search size={12} />
              <span>Search</span>
              <kbd className="text-[10px] bg-gray-700 px-1.5 py-0.5 rounded ml-2">Ctrl+K</kbd>
            </button>

            {sandbox && (
              <span className="flex items-center gap-1 text-xs bg-orange-500/20 text-orange-400 px-2.5 py-1 rounded-lg">
                <Shield size={12} /> SANDBOX
              </span>
            )}

            {!marketOpen && (
              <span className="flex items-center gap-1 text-xs bg-gray-800 text-gray-500 px-2.5 py-1 rounded-lg">
                <Clock size={12} /> Market Closed
              </span>
            )}

            {/* Connection status */}
            <div className="flex items-center gap-1.5">
              <div className={`w-2 h-2 rounded-full ${apiConnected ? "bg-emerald-400" : "bg-red-400"}`} />
              <span className="text-xs text-gray-500">
                {apiConnected ? (broker ? broker : "Live") : "Disconnected"}
              </span>
            </div>

            <ISTClock />
          </div>
        </header>

        {/* Module content */}
        <main className="flex-1 overflow-auto p-6">
          <ActiveComponent />
        </main>
      </div>

      {/* Command palette modal */}
      {cmdOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 bg-black/60" onClick={() => setCmdOpen(false)}>
          <div className="w-full max-w-md bg-gray-900 border border-gray-700 rounded-xl shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-800">
              <Search size={16} className="text-gray-500" />
              <input
                autoFocus
                value={cmdQuery}
                onChange={(e) => setCmdQuery(e.target.value)}
                placeholder="Search modules..."
                className="flex-1 bg-transparent outline-none text-sm text-gray-100 placeholder-gray-600"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && filteredModules.length > 0) {
                    setActiveModule(MODULES.indexOf(filteredModules[0]));
                    setCmdOpen(false);
                  }
                }}
              />
            </div>
            <div className="max-h-64 overflow-y-auto py-2">
              {filteredModules.map((mod) => {
                const Icon = mod.icon;
                const idx = MODULES.indexOf(mod);
                return (
                  <button
                    key={mod.name}
                    onClick={() => { setActiveModule(idx); setCmdOpen(false); }}
                    className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-gray-400 hover:bg-gray-800 hover:text-gray-100 transition-colors"
                  >
                    <Icon size={16} />
                    <span>{mod.name}</span>
                    <kbd className="ml-auto text-xs text-gray-600 bg-gray-800 px-1.5 py-0.5 rounded">{mod.key}</kbd>
                  </button>
                );
              })}
              {filteredModules.length === 0 && <p className="px-4 py-3 text-sm text-gray-600">No results</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
