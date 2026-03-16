import { useState, useCallback } from "react";
import { FlaskConical, BarChart3, List, GitCompare, History, Loader2, CheckCircle, AlertCircle } from "lucide-react";
import { runBacktest, getBacktestResult, getBacktestHistory, deleteBacktest } from "./services/api";
import ConfigPanel from "./panels/ConfigPanel";
import ResultsPanel from "./panels/ResultsPanel";
import TradeLog from "./panels/TradeLog";
import ComparePanel from "./panels/ComparePanel";
import HistoryPanel from "./panels/HistoryPanel";

const RESULT_TABS = [
  { id: "results", label: "Results", icon: BarChart3 },
  { id: "trades", label: "Trade Log", icon: List },
  { id: "compare", label: "Compare", icon: GitCompare },
  { id: "history", label: "History", icon: History },
];

const STATUS_MAP = {
  idle: { label: "Ready", color: "text-gray-400", Icon: FlaskConical },
  running: { label: "Running...", color: "text-blue-400", Icon: Loader2 },
  complete: { label: "Complete", color: "text-emerald-400", Icon: CheckCircle },
  error: { label: "Error", color: "text-red-400", Icon: AlertCircle },
};

export default function App() {
  const [status, setStatus] = useState("idle");
  const [resultTab, setResultTab] = useState("results");
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");

  const handleRun = useCallback(async (config) => {
    setStatus("running");
    setError("");
    setResult(null);

    try {
      const res = await runBacktest(config);

      // If we get a job_id, the result is the full response
      // If we get equity_curve directly, it's a synchronous result
      if (res.job_id) {
        // Poll for completion (simplified — real app would poll getBacktestStatus)
        const fullResult = await getBacktestResult(res.job_id);
        setResult(fullResult);
      } else {
        // Direct result
        setResult(res);
      }

      setStatus("complete");
      setResultTab("results");

      // Refresh history
      try {
        const hist = await getBacktestHistory();
        setHistory(hist?.runs || hist || []);
      } catch { /* */ }
    } catch (err) {
      setError(err.message || "Backtest failed");
      setStatus("error");
    }
  }, []);

  const handleLoadResult = useCallback(async (id) => {
    try {
      const res = await getBacktestResult(id);
      setResult(res);
      setResultTab("results");
      setStatus("complete");
      return res;
    } catch (err) {
      setError(err.message);
      return null;
    }
  }, []);

  const handleDelete = useCallback(async (id) => {
    try {
      await deleteBacktest(id);
      setHistory((prev) => prev.filter((h) => h.id !== id));
    } catch { /* */ }
  }, []);

  const statusInfo = STATUS_MAP[status];
  const StatusIcon = statusInfo.Icon;

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-gray-100">
      {/* Top bar */}
      <header className="flex items-center justify-between px-5 py-2.5 bg-gray-900/80 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-3">
          <FlaskConical size={18} className="text-blue-400" />
          <span className="font-bold text-sm">FlintTrade Backtest</span>
        </div>
        <div className="flex items-center gap-2">
          <StatusIcon size={14} className={`${statusInfo.color} ${status === "running" ? "animate-spin" : ""}`} />
          <span className={`text-xs ${statusInfo.color}`}>{statusInfo.label}</span>
          {error && <span className="text-xs text-red-400 ml-2 max-w-xs truncate">{error}</span>}
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 min-h-0">
        {/* Left: Config */}
        <aside className="w-80 shrink-0 border-r border-gray-800 bg-gray-900/30 p-4 overflow-y-auto">
          <ConfigPanel onRun={handleRun} running={status === "running"} />
        </aside>

        {/* Right: Results */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Tab bar */}
          <div className="flex gap-1 px-4 pt-3 pb-1">
            {RESULT_TABS.map((tab) => {
              const Icon = tab.icon;
              const active = resultTab === tab.id;
              return (
                <button key={tab.id} onClick={() => setResultTab(tab.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-colors ${
                    active ? "bg-gray-800 text-blue-400 font-semibold" : "text-gray-400 hover:text-gray-100 hover:bg-gray-800/50"
                  }`}>
                  <Icon size={13} />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-hidden p-4">
            {resultTab === "results" && <ResultsPanel result={result} />}
            {resultTab === "trades" && <TradeLog trades={result?.trades || []} />}
            {resultTab === "compare" && <ComparePanel history={history} onLoadResult={handleLoadResult} />}
            {resultTab === "history" && <HistoryPanel history={history} onLoad={handleLoadResult} onDelete={handleDelete} />}
          </div>
        </div>
      </div>
    </div>
  );
}
