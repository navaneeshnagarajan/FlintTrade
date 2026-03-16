import { useState, useMemo } from "react";
import { Download, ChevronLeft, ChevronRight, Search } from "lucide-react";

const PAGE_SIZE = 50;
const SORT_FIELDS = ["#", "entry_timestamp", "exit_timestamp", "symbol", "side", "quantity", "entry_price", "exit_price", "net_pnl", "pnl_pct", "bars_held"];

function fmtNum(v, dec = 2) {
  const n = Number(v) || 0;
  return n.toLocaleString("en-IN", { maximumFractionDigits: dec });
}

export default function TradeLog({ trades = [] }) {
  const [filter, setFilter] = useState("all"); // all | winners | losers
  const [exitFilter, setExitFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [sortField, setSortField] = useState("#");
  const [sortAsc, setSortAsc] = useState(true);
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    let list = trades.map((t, i) => ({
      ...t,
      idx: i + 1,
      pnl_pct: t.entry_price > 0 ? ((t.net_pnl || t.pnl || 0) / (t.entry_price * (t.quantity || 1))) * 100 : 0,
    }));

    if (filter === "winners") list = list.filter((t) => (t.net_pnl || t.pnl || 0) > 0);
    if (filter === "losers") list = list.filter((t) => (t.net_pnl || t.pnl || 0) <= 0);
    if (exitFilter !== "all") list = list.filter((t) => (t.exit_reason || "").toLowerCase() === exitFilter);
    if (search) list = list.filter((t) => (t.symbol || "").toLowerCase().includes(search.toLowerCase()));

    // Sort
    list.sort((a, b) => {
      let va, vb;
      if (sortField === "#") { va = a.idx; vb = b.idx; }
      else if (sortField === "net_pnl") { va = a.net_pnl || a.pnl || 0; vb = b.net_pnl || b.pnl || 0; }
      else if (sortField === "pnl_pct") { va = a.pnl_pct; vb = b.pnl_pct; }
      else { va = a[sortField] ?? ""; vb = b[sortField] ?? ""; }
      if (typeof va === "string") return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
      return sortAsc ? va - vb : vb - va;
    });

    return list;
  }, [trades, filter, exitFilter, search, sortField, sortAsc]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageData = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const toggleSort = (field) => {
    if (sortField === field) setSortAsc(!sortAsc);
    else { setSortField(field); setSortAsc(true); }
  };

  const exportCSV = () => {
    const header = ["#", "Entry Date", "Exit Date", "Symbol", "Action", "Qty", "Entry Price", "Exit Price", "P&L", "P&L%", "Bars Held", "Exit Reason"];
    const rows = filtered.map((t) => [
      t.idx, t.entry_timestamp, t.exit_timestamp, t.symbol, t.side, t.quantity,
      t.entry_price, t.exit_price, (t.net_pnl || t.pnl || 0).toFixed(2),
      t.pnl_pct.toFixed(2), t.bars_held, t.exit_reason || "",
    ]);
    const csv = [header, ...rows].map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "trade_log.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  if (trades.length === 0) {
    return <div className="flex items-center justify-center h-full text-gray-500 text-sm">No trades to display</div>;
  }

  return (
    <div className="flex flex-col h-full gap-3">
      {/* Controls */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex gap-1">
          {["all", "winners", "losers"].map((f) => (
            <button key={f} onClick={() => { setFilter(f); setPage(0); }}
              className={`px-2 py-1 rounded text-xs font-semibold capitalize ${filter === f ? "bg-emerald-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"}`}>
              {f}
            </button>
          ))}
        </div>
        <select value={exitFilter} onChange={(e) => { setExitFilter(e.target.value); setPage(0); }}
          className="bg-gray-800 rounded px-2 py-1 text-xs">
          <option value="all">All Exits</option>
          <option value="sl">Stop Loss</option>
          <option value="target">Target</option>
          <option value="signal">Signal</option>
          <option value="time">Time</option>
        </select>
        <div className="relative flex-1 max-w-xs">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-500" />
          <input value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            placeholder="Search symbol..."
            className="w-full bg-gray-800 rounded pl-7 pr-2 py-1 text-xs" />
        </div>
        <button onClick={exportCSV} className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-200 ml-auto">
          <Download size={12} /> CSV
        </button>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto bg-gray-900 rounded-lg border border-gray-800">
        <table className="w-full text-xs">
          <thead className="bg-gray-800 sticky top-0 z-10">
            <tr className="text-gray-400">
              {[
                { key: "#", label: "#" },
                { key: "entry_timestamp", label: "Entry Date" },
                { key: "exit_timestamp", label: "Exit Date" },
                { key: "symbol", label: "Symbol" },
                { key: "side", label: "Action" },
                { key: "quantity", label: "Qty" },
                { key: "entry_price", label: "Entry" },
                { key: "exit_price", label: "Exit" },
                { key: "net_pnl", label: "P&L (₹)" },
                { key: "pnl_pct", label: "P&L %" },
                { key: "bars_held", label: "Duration" },
              ].map((col) => (
                <th key={col.key}
                  onClick={() => toggleSort(col.key)}
                  className="px-2 py-2 text-right cursor-pointer hover:text-gray-200 select-none first:text-left">
                  {col.label}
                  {sortField === col.key && <span className="ml-0.5">{sortAsc ? "▲" : "▼"}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageData.map((t) => {
              const pnl = t.net_pnl || t.pnl || 0;
              const isWin = pnl > 0;
              return (
                <tr key={t.idx} className={`border-t border-gray-800/50 hover:bg-gray-800/30 ${isWin ? "bg-emerald-500/5" : "bg-red-500/5"}`}>
                  <td className="px-2 py-1 text-gray-500">{t.idx}</td>
                  <td className="px-2 py-1 font-mono">{(t.entry_timestamp || "").slice(0, 16)}</td>
                  <td className="px-2 py-1 font-mono">{(t.exit_timestamp || "").slice(0, 16)}</td>
                  <td className="px-2 py-1 font-semibold">{t.symbol}</td>
                  <td className={`px-2 py-1 text-right ${t.side === "BUY" ? "text-emerald-400" : "text-red-400"}`}>{t.side}</td>
                  <td className="px-2 py-1 text-right font-mono">{t.quantity}</td>
                  <td className="px-2 py-1 text-right font-mono">{fmtNum(t.entry_price)}</td>
                  <td className="px-2 py-1 text-right font-mono">{fmtNum(t.exit_price)}</td>
                  <td className={`px-2 py-1 text-right font-mono font-semibold ${isWin ? "text-emerald-400" : "text-red-400"}`}>
                    {pnl >= 0 ? "+" : ""}{fmtNum(pnl, 0)}
                  </td>
                  <td className={`px-2 py-1 text-right font-mono ${isWin ? "text-emerald-400" : "text-red-400"}`}>
                    {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-gray-400">{t.bars_held} bars</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>{filtered.length} trades</span>
        <div className="flex items-center gap-2">
          <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0}
            className="p-1 hover:bg-gray-800 rounded disabled:opacity-30"><ChevronLeft size={14} /></button>
          <span>Page {page + 1} of {totalPages}</span>
          <button onClick={() => setPage(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1}
            className="p-1 hover:bg-gray-800 rounded disabled:opacity-30"><ChevronRight size={14} /></button>
        </div>
      </div>
    </div>
  );
}
