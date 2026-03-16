import { useState } from "react";
import { Play, Pause, Square, Copy, Plus, Webhook, CheckCircle, AlertCircle, XCircle } from "lucide-react";

const STATUS_CFG = {
  ACTIVE: { color: "text-emerald-400", bg: "bg-emerald-500/10", icon: CheckCircle },
  PAUSED: { color: "text-yellow-400", bg: "bg-yellow-500/10", icon: AlertCircle },
  STOPPED: { color: "text-gray-400", bg: "bg-gray-500/10", icon: XCircle },
  ERROR: { color: "text-red-400", bg: "bg-red-500/10", icon: AlertCircle },
};

const SAMPLE_STRATEGIES = [
  { name: "EMA Crossover", status: "ACTIVE", pnl: 12500, winRate: 62, trades: 48, webhook: "/webhook/tradingview/ema_cross" },
  { name: "Straddle Sell", status: "ACTIVE", pnl: 34200, winRate: 71, trades: 22, webhook: "/webhook/tradingview/straddle" },
  { name: "ORB Breakout", status: "PAUSED", pnl: -3400, winRate: 45, trades: 15, webhook: "/webhook/tradingview/orb" },
  { name: "MACD + RSI", status: "STOPPED", pnl: 0, winRate: 0, trades: 0, webhook: "/webhook/tradingview/macd_rsi" },
];

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
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
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

      <div className="grid grid-cols-3 gap-3 mb-3">
        <div>
          <div className="text-[10px] text-gray-500">P&L</div>
          <div className={`text-sm font-mono font-bold ${strategy.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {strategy.pnl >= 0 ? "+" : ""}{strategy.pnl.toLocaleString()}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-gray-500">Win Rate</div>
          <div className="text-sm font-mono">{strategy.winRate}%</div>
        </div>
        <div>
          <div className="text-[10px] text-gray-500">Trades</div>
          <div className="text-sm font-mono">{strategy.trades}</div>
        </div>
      </div>

      <div className="flex items-center gap-1 text-[10px] text-gray-500 bg-gray-800 rounded px-2 py-1">
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
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-400">Strategies</h2>
        <button className="flex items-center gap-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded">
          <Plus size={14} /> New Strategy
        </button>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {SAMPLE_STRATEGIES.map((s) => <StrategyCard key={s.name} strategy={s} />)}
      </div>
    </div>
  );
}
