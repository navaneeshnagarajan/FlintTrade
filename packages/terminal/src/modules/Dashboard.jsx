import { useState, useEffect } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { TrendingUp, TrendingDown, Activity, AlertTriangle, Wallet, ShoppingCart } from "lucide-react";
import useWebSocket from "../hooks/useWebSocket";
import { getFunds, getPositionbook, getOrderbook } from "../services/api";

const INDICES = [
  { symbol: "NIFTY", exchange: "NSE_INDEX", name: "NIFTY 50" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX", name: "BANK NIFTY" },
  { symbol: "SENSEX", exchange: "BSE_INDEX", name: "SENSEX" },
  { symbol: "FINNIFTY", exchange: "NSE_INDEX", name: "FINNIFTY" },
  { symbol: "INDIA VIX", exchange: "NSE_INDEX", name: "VIX" },
];

function IndexCard({ data, name }) {
  const ltp = data?.ltp ?? 0;
  const change = data?.ltp && data?.prev_close ? data.ltp - data.prev_close : 0;
  const changePct = data?.prev_close ? (change / data.prev_close) * 100 : 0;
  const up = change >= 0;

  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <div className="text-xs text-gray-400 mb-1">{name}</div>
      <div className="text-xl font-bold font-mono">{ltp ? ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—"}</div>
      <div className={`flex items-center gap-1 text-sm mt-1 ${up ? "text-emerald-400" : "text-red-400"}`}>
        {up ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
        <span>{change >= 0 ? "+" : ""}{change.toFixed(2)}</span>
        <span>({changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%)</span>
      </div>
    </div>
  );
}

function MetricCard({ icon: Icon, label, value, sub, color = "text-gray-100" }) {
  return (
    <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
      <div className="flex items-center gap-2 text-xs text-gray-400 mb-2">
        <Icon size={14} /> {label}
      </div>
      <div className={`text-lg font-bold font-mono ${color}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  );
}

export default function Dashboard() {
  const instruments = INDICES.map((i) => ({ symbol: i.symbol, exchange: i.exchange }));
  const { ticks } = useWebSocket(instruments, "quote");

  const [pnl, setPnl] = useState({ realized: 0, unrealized: 0 });
  const [posCount, setPos] = useState(0);
  const [orderCounts, setOrders] = useState({ executed: 0, pending: 0, rejected: 0 });
  const [funds, setFunds] = useState({ available: 0, used: 0, total: 0 });
  const [equityCurve] = useState(() =>
    Array.from({ length: 30 }, (_, i) => ({
      day: `D-${30 - i}`,
      equity: 1000000 + Math.random() * 50000 - 25000 + i * 1000,
    }))
  );

  useEffect(() => {
    const load = async () => {
      try {
        const f = await getFunds();
        setFunds({
          available: parseFloat(f.available_balance || 0),
          used: parseFloat(f.used_margin || 0),
          total: parseFloat(f.total_balance || 0),
        });
      } catch { /* */ }
      try {
        const pos = await getPositionbook();
        if (Array.isArray(pos)) {
          setPos(pos.length);
          const ur = pos.reduce((s, p) => s + parseFloat(p.pnl || 0), 0);
          setPnl((prev) => ({ ...prev, unrealized: ur }));
        }
      } catch { /* */ }
      try {
        const ob = await getOrderbook();
        if (Array.isArray(ob)) {
          setOrders({
            executed: ob.filter((o) => o.status === "complete" || o.status === "COMPLETE").length,
            pending: ob.filter((o) => o.status === "open" || o.status === "OPEN" || o.status === "pending").length,
            rejected: ob.filter((o) => o.status === "rejected" || o.status === "REJECTED").length,
          });
        }
      } catch { /* */ }
    };
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  const utilPct = funds.total > 0 ? (funds.used / funds.total) * 100 : 0;

  return (
    <div className="space-y-4">
      {/* Market overview */}
      <div className="grid grid-cols-5 gap-3">
        {INDICES.map((idx) => (
          <IndexCard key={idx.symbol} data={ticks[`${idx.exchange}:${idx.symbol}`]} name={idx.name} />
        ))}
      </div>

      <div className="grid grid-cols-4 gap-3">
        <MetricCard
          icon={TrendingUp}
          label="Today's P&L"
          value={`${(pnl.realized + pnl.unrealized) >= 0 ? "+" : ""}${(pnl.realized + pnl.unrealized).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
          sub={`Realized: ${pnl.realized.toFixed(0)} | Unrealized: ${pnl.unrealized.toFixed(0)}`}
          color={(pnl.realized + pnl.unrealized) >= 0 ? "text-emerald-400" : "text-red-400"}
        />
        <MetricCard icon={Activity} label="Active Positions" value={posCount} sub={`Margin: ${funds.used.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`} />
        <MetricCard icon={ShoppingCart} label="Orders" value={orderCounts.executed} sub={`Pending: ${orderCounts.pending} | Rejected: ${orderCounts.rejected}`} />
        <MetricCard icon={Wallet} label="Funds Available" value={funds.available.toLocaleString("en-IN", { maximumFractionDigits: 0 })} />
      </div>

      {/* Equity curve + Fund utilization */}
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="text-sm text-gray-400 mb-2">Equity Curve (30 days)</div>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={equityCurve}>
              <defs>
                <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="day" tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
              <Tooltip contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8, fontSize: 12 }} />
              <Area type="monotone" dataKey="equity" stroke="#22c55e" fill="url(#eqGrad)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 flex flex-col justify-between">
          <div>
            <div className="text-sm text-gray-400 mb-3">Fund Utilization</div>
            <div className="text-2xl font-bold font-mono">{utilPct.toFixed(1)}%</div>
          </div>
          <div className="w-full bg-gray-800 rounded-full h-3 mt-4">
            <div
              className={`h-3 rounded-full transition-all ${utilPct > 80 ? "bg-red-500" : utilPct > 50 ? "bg-yellow-500" : "bg-emerald-500"}`}
              style={{ width: `${Math.min(utilPct, 100)}%` }}
            />
          </div>
          <div className="text-xs text-gray-500 mt-2">Used: {funds.used.toLocaleString()} / {funds.total.toLocaleString()}</div>
        </div>
      </div>
    </div>
  );
}
