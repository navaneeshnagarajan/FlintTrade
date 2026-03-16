import { useState, useEffect } from "react";
import { LayoutDashboard, TrendingUp, Activity, BookOpen, Shield } from "lucide-react";
import { ping, analyzerStatus } from "./services/api";
import StatusDot from "./components/StatusDot";
import Overview from "./tabs/Overview";
import PnLAnalytics from "./tabs/PnLAnalytics";
import SystemStatus from "./tabs/SystemStatus";
import TradeJournal from "./tabs/TradeJournal";

const TABS = [
  { name: "Overview", icon: LayoutDashboard, component: Overview },
  { name: "P&L Analytics", icon: TrendingUp, component: PnLAnalytics },
  { name: "System Status", icon: Activity, component: SystemStatus },
  { name: "Trade Journal", icon: BookOpen, component: TradeJournal },
];

function ISTClock() {
  const [time, setTime] = useState("");
  const [date, setDate] = useState("");
  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }));
      setDate(now.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric" }));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="text-right">
      <div className="text-xs font-mono text-gray-300">{time} IST</div>
      <div className="text-[10px] text-gray-500">{date}</div>
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState(0);
  const [connected, setConnected] = useState(false);
  const [sandbox, setSandbox] = useState(false);

  useEffect(() => {
    const check = async () => {
      try {
        await ping();
        setConnected(true);
        try {
          const s = await analyzerStatus();
          setSandbox(s?.analyzer === true || s?.status === "active");
        } catch { /* */ }
      } catch {
        setConnected(false);
      }
    };
    check();
    const id = setInterval(check, 30000);
    return () => clearInterval(id);
  }, []);

  const ActiveComponent = TABS[activeTab].component;

  return (
    <div className={`flex flex-col h-screen bg-gray-950 text-gray-100 ${sandbox ? "ring-2 ring-orange-500 ring-inset" : ""}`}>
      {/* Top bar */}
      <header className="flex items-center justify-between px-5 py-2.5 bg-gray-900/80 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-6">
          <span className="text-emerald-400 font-bold text-lg tracking-tight">FlintTrade</span>
          <nav className="flex gap-1">
            {TABS.map((tab, i) => {
              const Icon = tab.icon;
              const active = activeTab === i;
              return (
                <button key={tab.name} onClick={() => setActiveTab(i)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${
                    active ? "bg-gray-800 text-emerald-400 font-semibold" : "text-gray-400 hover:text-gray-100 hover:bg-gray-800/50"
                  }`}>
                  <Icon size={15} />
                  {tab.name}
                </button>
              );
            })}
          </nav>
        </div>
        <div className="flex items-center gap-4">
          {sandbox && (
            <span className="flex items-center gap-1 text-xs bg-orange-500/20 text-orange-400 px-2 py-0.5 rounded">
              <Shield size={12} /> SANDBOX
            </span>
          )}
          <div className="flex items-center gap-1.5">
            <StatusDot status={connected ? "connected" : "disconnected"} />
            <span className="text-xs text-gray-500">{connected ? "Live" : "Offline"}</span>
          </div>
          <ISTClock />
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 overflow-auto p-4">
        <ActiveComponent />
      </main>
    </div>
  );
}
