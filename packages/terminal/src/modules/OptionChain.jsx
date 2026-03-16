import { useState, useEffect } from "react";
import { getOptionChain, getExpiry } from "../services/api";

function fmtNum(v, dec = 2) {
  if (v == null || v === 0) return "—";
  return Number(v).toLocaleString("en-IN", { maximumFractionDigits: dec });
}

function OIBar({ ceOI, peOI, maxOI }) {
  if (maxOI === 0) return null;
  const ceW = (ceOI / maxOI) * 100;
  const peW = (peOI / maxOI) * 100;
  return (
    <div className="flex h-1.5 w-full gap-px">
      <div className="flex justify-end flex-1"><div className="bg-red-500/40 h-full rounded-l" style={{ width: `${ceW}%` }} /></div>
      <div className="flex-1"><div className="bg-emerald-500/40 h-full rounded-r" style={{ width: `${peW}%` }} /></div>
    </div>
  );
}

export default function OptionChain() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [exchange, setExchange] = useState("NFO");
  const [expiries, setExpiries] = useState([]);
  const [selectedExpiry, setSelectedExpiry] = useState("");
  const [chain, setChain] = useState([]);
  const [spotPrice, setSpotPrice] = useState(0);
  const [loading, setLoading] = useState(false);

  // Fetch expiries
  useEffect(() => {
    (async () => {
      try {
        const data = await getExpiry(symbol, exchange);
        const list = data?.expiry || data?.expiries || [];
        setExpiries(Array.isArray(list) ? list : []);
        if (list.length > 0) setSelectedExpiry(list[0]);
      } catch { setExpiries([]); }
    })();
  }, [symbol, exchange]);

  // Fetch chain
  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    (async () => {
      try {
        const data = await getOptionChain(symbol, exchange);
        const strikes = data?.strikes || [];
        setChain(strikes);
        if (strikes.length > 0) {
          const midIdx = Math.floor(strikes.length / 2);
          setSpotPrice(strikes[midIdx]?.strike_price || 0);
        }
      } catch { setChain([]); }
      setLoading(false);
    })();
  }, [symbol, exchange, selectedExpiry]);

  const maxOI = Math.max(...chain.map((s) => Math.max(s.ce_oi || 0, s.pe_oi || 0)), 1);
  const totalCeOI = chain.reduce((s, r) => s + (r.ce_oi || 0), 0);
  const totalPeOI = chain.reduce((s, r) => s + (r.pe_oi || 0), 0);
  const pcr = totalCeOI > 0 ? (totalPeOI / totalCeOI).toFixed(2) : "—";

  const atmStrike = chain.reduce((best, s) => {
    return Math.abs(s.strike_price - spotPrice) < Math.abs(best - spotPrice) ? s.strike_price : best;
  }, chain[0]?.strike_price || 0);

  return (
    <div className="flex flex-col gap-3 h-full">
      {/* Controls */}
      <div className="flex items-center gap-2 text-xs">
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} className="bg-gray-800 rounded px-2 py-1 w-28" />
        <select value={exchange} onChange={(e) => setExchange(e.target.value)} className="bg-gray-800 rounded px-2 py-1">
          <option>NFO</option><option>BFO</option><option>CDS</option><option>MCX</option>
        </select>
        <div className="flex gap-1">
          {expiries.slice(0, 5).map((exp) => (
            <button key={exp} onClick={() => setSelectedExpiry(exp)}
              className={`px-2 py-0.5 rounded ${selectedExpiry === exp ? "bg-emerald-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"}`}>
              {String(exp).slice(-4) || exp}
            </button>
          ))}
        </div>
        <div className="ml-auto flex gap-4 text-gray-400">
          <span>PCR: <strong className="text-gray-100">{pcr}</strong></span>
          <span>CE OI: <strong className="text-red-400">{fmtNum(totalCeOI, 0)}</strong></span>
          <span>PE OI: <strong className="text-emerald-400">{fmtNum(totalPeOI, 0)}</strong></span>
        </div>
      </div>

      {/* Chain table */}
      <div className="flex-1 overflow-auto bg-gray-900 rounded-lg border border-gray-800">
        {loading ? (
          <div className="flex items-center justify-center h-64 text-gray-500">Loading option chain...</div>
        ) : (
          <table className="w-full text-xs">
            <thead className="bg-gray-800 sticky top-0 z-10">
              <tr>
                <th colSpan={6} className="text-center py-1.5 text-red-400 border-b border-gray-700">CALLS</th>
                <th className="text-center py-1.5 border-b border-gray-700">STRIKE</th>
                <th colSpan={6} className="text-center py-1.5 text-emerald-400 border-b border-gray-700">PUTS</th>
              </tr>
              <tr className="text-gray-400">
                <th className="px-2 py-1 text-right">OI</th>
                <th className="px-2 py-1 text-right">Vol</th>
                <th className="px-2 py-1 text-right">IV</th>
                <th className="px-2 py-1 text-right">Bid</th>
                <th className="px-2 py-1 text-right">Ask</th>
                <th className="px-2 py-1 text-right">LTP</th>
                <th className="px-2 py-1 text-center font-bold text-gray-200">Strike</th>
                <th className="px-2 py-1 text-right">LTP</th>
                <th className="px-2 py-1 text-right">Bid</th>
                <th className="px-2 py-1 text-right">Ask</th>
                <th className="px-2 py-1 text-right">IV</th>
                <th className="px-2 py-1 text-right">Vol</th>
                <th className="px-2 py-1 text-right">OI</th>
              </tr>
            </thead>
            <tbody>
              {chain.map((s) => {
                const isATM = s.strike_price === atmStrike;
                const itm_ce = s.strike_price < spotPrice;
                const itm_pe = s.strike_price > spotPrice;
                return (
                  <tr key={s.strike_price} className={`border-t border-gray-800/50 hover:bg-gray-800/30 ${isATM ? "bg-gray-800/60 ring-1 ring-emerald-500/30" : ""}`}>
                    <td className={`px-2 py-1 text-right font-mono ${itm_ce ? "bg-red-500/5" : ""}`}>{fmtNum(s.ce_oi, 0)}</td>
                    <td className={`px-2 py-1 text-right font-mono ${itm_ce ? "bg-red-500/5" : ""}`}>{fmtNum(s.ce_volume, 0)}</td>
                    <td className={`px-2 py-1 text-right font-mono ${itm_ce ? "bg-red-500/5" : ""}`}>{fmtNum(s.ce_iv, 1)}</td>
                    <td className={`px-2 py-1 text-right font-mono ${itm_ce ? "bg-red-500/5" : ""}`}>{fmtNum(s.ce_bid)}</td>
                    <td className={`px-2 py-1 text-right font-mono ${itm_ce ? "bg-red-500/5" : ""}`}>{fmtNum(s.ce_ask)}</td>
                    <td className={`px-2 py-1 text-right font-mono font-semibold ${itm_ce ? "bg-red-500/5" : ""}`}>{fmtNum(s.ce_ltp)}</td>
                    <td className={`px-2 py-1 text-center font-bold font-mono ${isATM ? "text-emerald-400" : "text-gray-300"}`}>{s.strike_price}</td>
                    <td className={`px-2 py-1 text-right font-mono font-semibold ${itm_pe ? "bg-emerald-500/5" : ""}`}>{fmtNum(s.pe_ltp)}</td>
                    <td className={`px-2 py-1 text-right font-mono ${itm_pe ? "bg-emerald-500/5" : ""}`}>{fmtNum(s.pe_bid)}</td>
                    <td className={`px-2 py-1 text-right font-mono ${itm_pe ? "bg-emerald-500/5" : ""}`}>{fmtNum(s.pe_ask)}</td>
                    <td className={`px-2 py-1 text-right font-mono ${itm_pe ? "bg-emerald-500/5" : ""}`}>{fmtNum(s.pe_iv, 1)}</td>
                    <td className={`px-2 py-1 text-right font-mono ${itm_pe ? "bg-emerald-500/5" : ""}`}>{fmtNum(s.pe_volume, 0)}</td>
                    <td className={`px-2 py-1 text-right font-mono ${itm_pe ? "bg-emerald-500/5" : ""}`}>{fmtNum(s.pe_oi, 0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
