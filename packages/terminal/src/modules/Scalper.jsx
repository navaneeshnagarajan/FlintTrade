import { useState, useCallback } from "react";
import { ArrowUpCircle, ArrowDownCircle, X, Ban, ListOrdered, Zap, ZapOff } from "lucide-react";
import Chart from "../components/Chart";
import useWebSocket from "../hooks/useWebSocket";
import { placeOrder, cancelAllOrders, closePosition, getPositionbook } from "../services/api";
import { useEffect } from "react";

const TIMEFRAMES = ["1m", "3m", "5m", "15m", "1h", "D"];

export default function Scalper() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [exchange] = useState("NFO");
  const [spotExchange] = useState("NSE_INDEX");
  const [expiry, setExpiry] = useState("");
  const [ceStrike, setCeStrike] = useState("ATM");
  const [peStrike, setPeStrike] = useState("ATM");
  const [qty, setQty] = useState(75);
  const [slPoints, setSlPoints] = useState(20);
  const [targetPoints, setTargetPoints] = useState(40);
  const [product, setProduct] = useState("MIS");
  const [orderType, setOrderType] = useState("MARKET");
  const [tf, setTf] = useState("5m");
  const [oneClick, setOneClick] = useState(false);
  const [positions, setPositions] = useState([]);
  const [showOC, setShowOC] = useState(false);

  const instruments = [{ symbol, exchange: spotExchange }];
  const { ticks } = useWebSocket(instruments, "quote");
  const spotData = ticks[`${spotExchange}:${symbol}`];

  useEffect(() => {
    const load = async () => {
      try {
        const pos = await getPositionbook();
        if (Array.isArray(pos)) setPositions(pos);
      } catch { /* */ }
    };
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const execOrder = useCallback(async (action, optType) => {
    const confirm = oneClick || window.confirm(`${action} ${optType}? Qty: ${qty}`);
    if (!confirm) return;
    try {
      await placeOrder({
        strategy: "Flint",
        symbol: `${symbol}${ceStrike}${optType}`,
        action,
        exchange,
        pricetype: orderType,
        product,
        quantity: String(qty),
        price: "0",
        trigger_price: "0",
        disclosed_quantity: "0",
      });
    } catch (err) {
      console.error("Order failed:", err);
    }
  }, [symbol, exchange, ceStrike, qty, product, orderType, oneClick]);

  const exitAll = useCallback(async () => {
    const ok = oneClick || window.confirm("Exit ALL positions?");
    if (ok) await closePosition("Flint").catch(() => {});
  }, [oneClick]);

  const cancelAll = useCallback(async () => {
    await cancelAllOrders("Flint").catch(() => {});
  }, []);

  const lotInc = () => setQty((q) => q + 75);
  const lotDec = () => setQty((q) => Math.max(75, q - 75));

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Config bar */}
      <div className="flex items-center gap-2 flex-wrap bg-gray-900 p-2 rounded-lg border border-gray-800 text-xs">
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} className="bg-gray-800 rounded px-2 py-1 w-24 text-center" />
        <select value={expiry} onChange={(e) => setExpiry(e.target.value)} className="bg-gray-800 rounded px-2 py-1">
          <option value="">Current</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
        </select>
        <input value={ceStrike} onChange={(e) => setCeStrike(e.target.value)} className="bg-gray-800 rounded px-2 py-1 w-20 text-center" placeholder="CE Strike" />
        <input value={peStrike} onChange={(e) => setPeStrike(e.target.value)} className="bg-gray-800 rounded px-2 py-1 w-20 text-center" placeholder="PE Strike" />
        <div className="flex items-center gap-1">
          <button onClick={lotDec} className="bg-gray-700 rounded px-1.5 py-0.5 hover:bg-gray-600">-</button>
          <span className="w-12 text-center font-mono">{qty}</span>
          <button onClick={lotInc} className="bg-gray-700 rounded px-1.5 py-0.5 hover:bg-gray-600">+</button>
        </div>
        <span className="text-gray-500">SL:</span>
        <input type="number" value={slPoints} onChange={(e) => setSlPoints(+e.target.value)} className="bg-gray-800 rounded px-2 py-1 w-14 text-center" />
        <span className="text-gray-500">TGT:</span>
        <input type="number" value={targetPoints} onChange={(e) => setTargetPoints(+e.target.value)} className="bg-gray-800 rounded px-2 py-1 w-14 text-center" />
        <select value={product} onChange={(e) => setProduct(e.target.value)} className="bg-gray-800 rounded px-2 py-1">
          <option>MIS</option><option>NRML</option>
        </select>
        <select value={orderType} onChange={(e) => setOrderType(e.target.value)} className="bg-gray-800 rounded px-2 py-1">
          <option>MARKET</option><option>LIMIT</option>
        </select>
        {TIMEFRAMES.map((t) => (
          <button key={t} onClick={() => setTf(t)} className={`px-2 py-0.5 rounded ${tf === t ? "bg-emerald-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"}`}>{t}</button>
        ))}
        <button onClick={() => setOneClick((v) => !v)} className={`flex items-center gap-1 px-2 py-0.5 rounded ${oneClick ? "bg-yellow-600 text-white" : "bg-gray-800 text-gray-400"}`}>
          {oneClick ? <Zap size={12} /> : <ZapOff size={12} />} 1-Click
        </button>
        <button onClick={() => setShowOC((v) => !v)} className="bg-gray-800 text-gray-400 px-2 py-0.5 rounded hover:bg-gray-700">OC</button>
      </div>

      {/* 3 synced charts */}
      <div className="grid grid-cols-3 gap-2 flex-1 min-h-0">
        <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
          <div className="text-[10px] text-gray-500 px-2 pt-1">CE</div>
          <Chart symbol={`${symbol}${ceStrike}CE`} exchange={exchange} interval={tf} height={250} />
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
          <div className="text-[10px] text-gray-500 px-2 pt-1">SPOT {spotData?.ltp ? `${spotData.ltp.toLocaleString()}` : ""}</div>
          <Chart symbol={symbol} exchange={spotExchange} interval={tf} height={250} />
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
          <div className="text-[10px] text-gray-500 px-2 pt-1">PE</div>
          <Chart symbol={`${symbol}${peStrike}PE`} exchange={exchange} interval={tf} height={250} />
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2">
        <button onClick={() => execOrder("BUY", "CE")} className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white py-2 rounded font-semibold flex items-center justify-center gap-1">
          <ArrowUpCircle size={16} /> Buy CE
        </button>
        <button onClick={() => execOrder("SELL", "CE")} className="flex-1 bg-red-600 hover:bg-red-500 text-white py-2 rounded font-semibold flex items-center justify-center gap-1">
          <ArrowDownCircle size={16} /> Sell CE
        </button>
        <button onClick={() => execOrder("BUY", "PE")} className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white py-2 rounded font-semibold flex items-center justify-center gap-1">
          <ArrowUpCircle size={16} /> Buy PE
        </button>
        <button onClick={() => execOrder("SELL", "PE")} className="flex-1 bg-red-600 hover:bg-red-500 text-white py-2 rounded font-semibold flex items-center justify-center gap-1">
          <ArrowDownCircle size={16} /> Sell PE
        </button>
        <button onClick={exitAll} className="bg-red-700 hover:bg-red-600 text-white px-4 py-2 rounded font-semibold flex items-center gap-1">
          <X size={16} /> Exit All
        </button>
        <button onClick={cancelAll} className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded font-semibold flex items-center gap-1">
          <Ban size={16} /> Cancel All
        </button>
      </div>

      {/* Positions panel */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-auto max-h-48">
        <table className="w-full text-xs">
          <thead className="bg-gray-800 sticky top-0">
            <tr className="text-gray-400">
              <th className="px-3 py-1.5 text-left">Symbol</th>
              <th className="px-3 py-1.5 text-right">Qty</th>
              <th className="px-3 py-1.5 text-right">Avg</th>
              <th className="px-3 py-1.5 text-right">LTP</th>
              <th className="px-3 py-1.5 text-right">P&L</th>
              <th className="px-3 py-1.5 text-center">Exit</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-gray-500">No open positions</td></tr>
            ) : positions.map((p, i) => {
              const pnl = parseFloat(p.pnl || 0);
              return (
                <tr key={i} className="border-t border-gray-800 hover:bg-gray-800/50">
                  <td className="px-3 py-1.5">{p.symbol}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{p.quantity}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{p.average_price}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{p.ltp}</td>
                  <td className={`px-3 py-1.5 text-right font-mono ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>{pnl.toFixed(0)}</td>
                  <td className="px-3 py-1.5 text-center">
                    <div className="flex gap-1 justify-center">
                      {[25, 50, 75, 100].map((pct) => (
                        <button key={pct} className="text-[10px] bg-gray-700 hover:bg-gray-600 px-1 rounded">{pct}%</button>
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
