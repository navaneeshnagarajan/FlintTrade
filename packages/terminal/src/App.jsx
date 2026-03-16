import { useState, useCallback, useEffect, useMemo } from "react";
import {
  LayoutDashboard, Crosshair, Table2, BarChart3, Puzzle,
  FlaskConical, Briefcase, BookOpen, Settings as SettingsIcon,
  Wifi, WifiOff, Search, Shield,
} from "lucide-react";
import useKeyboard from "./hooks/useKeyboard";
import useWebSocket from "./hooks/useWebSocket";

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

function ISTClock() {
  const [time, setTime] = useState("");
  useEffect(() => {
    const tick = () => setTime(new Date().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return <span className="text-xs text-gray-400 font-mono">{time} IST</span>;
}

export default function App() {
  const [activeModule, setActiveModule] = useState(0);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [cmdQuery, setCmdQuery] = useState("");
  const [sandbox, setSandbox] = useState(false);
  const [sidebarHover, setSidebarHover] = useState(false);

  const { connected } = useWebSocket();

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
      {/* Sidebar */}
      <aside
        className="flex flex-col items-center py-3 bg-gray-900 border-r border-gray-800 transition-all duration-200 shrink-0"
        style={{ width: sidebarHover ? 160 : 48 }}
        onMouseEnter={() => setSidebarHover(true)}
        onMouseLeave={() => setSidebarHover(false)}
      >
        <div className="mb-4 text-emerald-400 font-bold text-lg">{sidebarHover ? "Flint" : "F"}</div>
        {MODULES.map((mod, i) => {
          const Icon = mod.icon;
          const active = activeModule === i;
          return (
            <button
              key={mod.name}
              onClick={() => setActiveModule(i)}
              title={`${mod.name} (${mod.key})`}
              className={`flex items-center gap-2 w-full px-3 py-2 text-sm rounded-md transition-colors ${
                active ? "bg-gray-800 text-emerald-400" : "text-gray-400 hover:text-gray-100 hover:bg-gray-800/50"
              }`}
            >
              <Icon size={18} />
              {sidebarHover && <span className="truncate">{mod.name}</span>}
            </button>
          );
        })}
      </aside>

      {/* Main area */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Top bar */}
        <header className="flex items-center justify-between px-4 py-2 bg-gray-900/80 border-b border-gray-800 shrink-0">
          <div className="flex items-center gap-3">
            <span className="font-semibold text-sm">{MODULES[activeModule].name}</span>
            <span className="text-xs text-gray-500">{MODULES[activeModule].key}</span>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => { setCmdOpen(true); setCmdQuery(""); }}
              className="flex items-center gap-1.5 text-xs text-gray-400 bg-gray-800 rounded px-2.5 py-1 hover:bg-gray-700"
            >
              <Search size={12} /> <span>Search</span>
              <kbd className="text-[10px] bg-gray-700 px-1 rounded">Ctrl+K</kbd>
            </button>
            {sandbox && (
              <span className="flex items-center gap-1 text-xs bg-orange-500/20 text-orange-400 px-2 py-0.5 rounded">
                <Shield size={12} /> SANDBOX
              </span>
            )}
            <div className="flex items-center gap-1.5">
              {connected ? <Wifi size={14} className="text-emerald-400" /> : <WifiOff size={14} className="text-red-400" />}
              <span className="text-xs text-gray-500">{connected ? "Live" : "Offline"}</span>
            </div>
            <ISTClock />
          </div>
        </header>

        {/* Module content */}
        <main className="flex-1 overflow-auto p-4">
          <ActiveComponent />
        </main>
      </div>

      {/* Command palette modal */}
      {cmdOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 bg-black/60" onClick={() => setCmdOpen(false)}>
          <div className="w-full max-w-md bg-gray-900 border border-gray-700 rounded-xl shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-800">
              <Search size={16} className="text-gray-400" />
              <input
                autoFocus
                value={cmdQuery}
                onChange={(e) => setCmdQuery(e.target.value)}
                placeholder="Search modules, symbols..."
                className="flex-1 bg-transparent outline-none text-sm text-gray-100 placeholder-gray-500"
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
                    className="flex items-center gap-3 w-full px-4 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-gray-100"
                  >
                    <Icon size={16} />
                    <span>{mod.name}</span>
                    <kbd className="ml-auto text-xs text-gray-500 bg-gray-800 px-1.5 rounded">{mod.key}</kbd>
                  </button>
                );
              })}
              {filteredModules.length === 0 && <p className="px-4 py-2 text-sm text-gray-500">No results</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
