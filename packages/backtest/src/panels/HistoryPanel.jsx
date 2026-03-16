import { useState, useMemo } from "react";
import { Trash2, ChevronDown, ChevronUp } from "lucide-react";

export default function HistoryPanel({ history = [], onLoad, onDelete }) {
  const [sortField, setSortField] = useState("run_date");
  const [sortAsc, setSortAsc] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);

  const sorted = useMemo(() => {
    return [...history].sort((a, b) => {
      const va = a[sortField] ?? "";
      const vb = b[sortField] ?? "";
      if (typeof va === "number" && typeof vb === "number") return sortAsc ? va - vb : vb - va;
      return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
    });
  }, [history, sortField, sortAsc]);

  const toggleSort = (field) => {
    if (sortField === field) setSortAsc(!sortAsc);
    else { setSortField(field); setSortAsc(true); }
  };

  const SortIcon = ({ field }) => {
    if (sortField !== field) return null;
    return sortAsc ? <ChevronUp size={10} className="inline ml-0.5" /> : <ChevronDown size={10} className="inline ml-0.5" />;
  };

  const handleDelete = (id) => {
    if (confirmDelete === id) {
      onDelete?.(id);
      setConfirmDelete(null);
    } else {
      setConfirmDelete(id);
      setTimeout(() => setConfirmDelete(null), 3000);
    }
  };

  if (history.length === 0) {
    return <div className="flex items-center justify-center h-full text-gray-500 text-sm">No backtest history yet</div>;
  }

  return (
    <div className="overflow-auto bg-gray-900 rounded-lg border border-gray-800">
      <table className="w-full text-xs">
        <thead className="bg-gray-800 sticky top-0 z-10">
          <tr className="text-gray-400">
            {[
              { key: "strategy", label: "Strategy" },
              { key: "symbol", label: "Symbol" },
              { key: "start_date", label: "Start" },
              { key: "end_date", label: "End" },
              { key: "total_return_pct", label: "Return" },
              { key: "sharpe_ratio", label: "Sharpe" },
              { key: "max_drawdown_pct", label: "Max DD" },
              { key: "run_date", label: "Run Date" },
            ].map((col) => (
              <th key={col.key} onClick={() => toggleSort(col.key)}
                className="px-3 py-2 text-left cursor-pointer hover:text-gray-200 select-none">
                {col.label}<SortIcon field={col.key} />
              </th>
            ))}
            <th className="px-3 py-2 w-16"></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((h) => (
            <tr key={h.id} className="border-t border-gray-800 hover:bg-gray-800/30 cursor-pointer"
              onClick={() => onLoad?.(h.id)}>
              <td className="px-3 py-2 font-semibold">{h.strategy}</td>
              <td className="px-3 py-2">{h.symbol}</td>
              <td className="px-3 py-2 font-mono text-gray-400">{h.start_date}</td>
              <td className="px-3 py-2 font-mono text-gray-400">{h.end_date}</td>
              <td className={`px-3 py-2 font-mono font-semibold ${(h.total_return_pct || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {(h.total_return_pct || 0) >= 0 ? "+" : ""}{(h.total_return_pct || 0).toFixed(2)}%
              </td>
              <td className="px-3 py-2 font-mono">{(h.sharpe_ratio || 0).toFixed(2)}</td>
              <td className="px-3 py-2 font-mono text-red-400">-{Math.abs(h.max_drawdown_pct || 0).toFixed(2)}%</td>
              <td className="px-3 py-2 text-gray-400">{h.run_date || "—"}</td>
              <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                <button onClick={() => handleDelete(h.id)}
                  className={`p-1 rounded hover:bg-gray-700 ${confirmDelete === h.id ? "text-red-400" : "text-gray-500"}`}
                  title={confirmDelete === h.id ? "Click again to confirm" : "Delete"}>
                  <Trash2 size={13} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
