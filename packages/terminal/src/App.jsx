import { useState, useEffect, useMemo } from "react";
import {
  LayoutDashboard, TrendingUp, Table2, BarChart3,
  Search, FlaskConical, Bot, Settings as SettingsIcon,
  Shield, Clock,
} from "lucide-react";
import useKeyboard from "./hooks/useKeyboard";
import { ping } from "./services/api";

import Dashboard from "./modules/Dashboard";
import Scalper from "./modules/Scalper";
import OptionChain from "./modules/OptionChain";
import Backtest from "./modules/Backtest";
import Settings from "./modules/Settings";

const MODULES = [
  { name: "Dashboard", icon: LayoutDashboard, key: "F1", component: Dashboard },
  { name: "Terminal", icon: TrendingUp, key: "F2", component: null },
  { name: "Option Chain", icon: Table2, key: "F3", component: OptionChain },
  { name: "Charts", icon: BarChart3, key: "F4", component: null },
  { name: "Screener", icon: Search, key: "F5", component: null },
  { name: "Backtest", icon: FlaskConical, key: "F6", component: Backtest },
  { name: "Strategies", icon: Bot, key: "F7", component: null },
  { name: "Settings", icon: SettingsIcon, key: "F8", component: Settings },
];

function Placeholder({ name }) {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <div className="text-text-muted text-lg font-medium mb-1">{name}</div>
        <div className="text-text-muted/50 text-sm">Coming Soon</div>
      </div>
    </div>
  );
}

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
  return <span className="text-xs font-mono text-text-muted">{time} IST</span>;
}

export default function App() {
  const [activeModule, setActiveModule] = useState(0);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [cmdQuery, setCmdQuery] = useState("");
  const [sandbox, setSandbox] = useState(false);
  const [apiConnected, setApiConnected] = useState(false);
  const [broker, setBroker] = useState("");
  const [marketOpen, setMarketOpen] = useState(isMarketOpen);

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

  const mod = MODULES[activeModule];
  const ActiveComponent = mod.component;

  const filteredModules = MODULES.filter((m) =>
    m.name.toLowerCase().includes(cmdQuery.toLowerCase())
  );

  return (
    <div className={`flex h-screen bg-surface-base text-text-primary ${sandbox ? "ring-2 ring-warning ring-inset" : ""}`}>
      {/* Sidebar — 48px, icons only */}
      <aside className="flex flex-col items-center py-3 bg-surface-base border-r border-border-default w-12 shrink-0">
        <div className="mb-4 text-profit font-bold text-sm">F</div>
        {MODULES.map((m, i) => {
          const Icon = m.icon;
          const active = activeModule === i;
          return (
            <button
              key={m.name}
              onClick={() => setActiveModule(i)}
              title={`${m.name} (${m.key})`}
              className={`flex items-center justify-center w-9 h-9 mb-0.5 rounded-lg transition-colors ${
                active
                  ? "bg-surface-card text-text-primary border border-border-default"
                  : "text-text-muted hover:text-text-secondary hover:bg-surface-card/50"
              }`}
            >
              <Icon size={18} />
            </button>
          );
        })}
      </aside>

      {/* Main area */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Top bar — 40px */}
        <header className="flex items-center justify-between px-4 h-10 bg-surface-card border-b border-border-default shrink-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm text-text-primary">{mod.name}</span>
            <kbd className="text-[10px] text-text-muted bg-surface-base px-1.5 py-0.5 rounded border border-border-default">{mod.key}</kbd>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => { setCmdOpen(true); setCmdQuery(""); }}
              className="flex items-center gap-1.5 text-xs text-text-muted bg-surface-base rounded-lg px-2.5 py-1 hover:bg-surface-hover hover:text-text-secondary transition-colors border border-border-default"
            >
              <Search size={11} />
              <span>Search</span>
              <kbd className="text-[9px] bg-surface-card px-1 py-0.5 rounded ml-1.5">^K</kbd>
            </button>

            {sandbox && (
              <span className="flex items-center gap-1 text-xs bg-warning/10 text-warning px-2 py-0.5 rounded-lg">
                <Shield size={11} /> SANDBOX
              </span>
            )}

            {!marketOpen && (
              <span className="flex items-center gap-1 text-xs bg-surface-base text-text-muted px-2 py-0.5 rounded-lg border border-border-default">
                <Clock size={11} /> Closed
              </span>
            )}

            <div className="flex items-center gap-1.5">
              <div className={`w-1.5 h-1.5 rounded-full ${apiConnected ? "bg-profit" : "bg-loss"}`} />
              <span className="text-xs text-text-muted">
                {apiConnected ? (broker || "Live") : "Disconnected"}
              </span>
            </div>

            <ISTClock />
          </div>
        </header>

        {/* Module content */}
        <main className="flex-1 overflow-auto p-4 bg-surface-base">
          {ActiveComponent ? <ActiveComponent /> : <Placeholder name={mod.name} />}
        </main>
      </div>

      {/* Command palette */}
      {cmdOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-black/60" onClick={() => setCmdOpen(false)}>
          <div className="w-full max-w-md bg-surface-card border border-border-default rounded-lg shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border-default">
              <Search size={14} className="text-text-muted" />
              <input
                autoFocus
                value={cmdQuery}
                onChange={(e) => setCmdQuery(e.target.value)}
                placeholder="Search modules..."
                className="flex-1 bg-transparent outline-none text-sm text-text-primary placeholder-text-muted font-sans"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && filteredModules.length > 0) {
                    setActiveModule(MODULES.indexOf(filteredModules[0]));
                    setCmdOpen(false);
                  }
                }}
              />
            </div>
            <div className="max-h-64 overflow-y-auto py-1">
              {filteredModules.map((m) => {
                const Icon = m.icon;
                const idx = MODULES.indexOf(m);
                return (
                  <button
                    key={m.name}
                    onClick={() => { setActiveModule(idx); setCmdOpen(false); }}
                    className="flex items-center gap-3 w-full px-3 py-2 text-sm text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors"
                  >
                    <Icon size={15} />
                    <span>{m.name}</span>
                    <kbd className="ml-auto text-[10px] text-text-muted bg-surface-base px-1.5 py-0.5 rounded">{m.key}</kbd>
                  </button>
                );
              })}
              {filteredModules.length === 0 && <p className="px-3 py-2 text-sm text-text-muted">No results</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
