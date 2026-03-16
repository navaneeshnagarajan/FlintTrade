import { useState } from "react";
import { Play, Pause, Square, Copy, Plus, Webhook, CheckCircle, AlertCircle, XCircle } from "lucide-react";

const STATUS_CFG = {
  ACTIVE: { color: "text-emerald-400", bg: "bg-emerald-500/10", icon: CheckCircle },
  PAUSED: { color: "text-yellow-400", bg: "bg-yellow-500/10", icon: AlertCircle },
  STOPPED: { color: "text-gray-500", bg: "bg-gray-500/10", icon: XCircle },
  ERROR: { color: "text-red-400", bg: "bg-red-500/10", icon: AlertCircle },
};

function StrategyCard({ strategy }) {
  const cfg = STATUS_CFG[strategy.status] || STATUS_CFG.STOPPED;
  const Icon = cfg.icon;
  const [copied, setCopied] = useState(false);

  const copyWebhook = () => {
    navigator.clipboard.writeText(window.location.origin + strategy.webhook).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="font-semibold text-sm">{strategy.name}</h3>
          <div className={`flex items-center gap-1 text-xs mt-1 ${cfg.color}`}>
            <Icon size={12} /> {strategy.status}
          </div>
        </div>
        <div className="flex gap-1">
          <button className="p-1.5 rounded hover:bg-gray-800 text-emerald-400" title="Start"><Play size={14} /></button>
          <button className="p-1.5 rounded hover:bg-gray-800 text-yellow-400" title="Pause"><Pause size={14} /></button>
          <button className="p-1.5 rounded hover:bg-gray-800 text-red-400" title="Stop"><Square size={14} /></button>
        </div>
      </div>

      <div className="flex items-center gap-1 text-[10px] text-gray-600 bg-gray-800 rounded-lg px-2.5 py-1.5">
        <Webhook size={10} />
        <span className="truncate flex-1 font-mono">{strategy.webhook}</span>
        <button onClick={copyWebhook} className="shrink-0 hover:text-gray-300">
          {copied ? <CheckCircle size={10} className="text-emerald-400" /> : <Copy size={10} />}
        </button>
      </div>
    </div>
  );
}

export default function Strategy() {
  // Strategies are configured via OpenAlgo webhooks — no mock data.
  // This will be populated when the strategy management backend is built.
  const [strategies] = useState([]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm text-gray-500 uppercase tracking-wide">Strategies</h2>
        <button className="flex items-center gap-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-lg transition-colors">
          <Plus size={14} /> New Strategy
        </button>
      </div>

      {strategies.length === 0 ? (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-10 text-center">
          <Webhook size={32} className="text-gray-700 mx-auto mb-3" />
          <p className="text-gray-500 text-sm">No strategies configured</p>
          <p className="text-gray-600 text-xs mt-1">Create a strategy to start receiving TradingView webhook signals</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {strategies.map((s) => <StrategyCard key={s.name} strategy={s} />)}
        </div>
      )}
    </div>
  );
}
