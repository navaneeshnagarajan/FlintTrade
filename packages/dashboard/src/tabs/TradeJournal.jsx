import { useState, useMemo } from "react";
import { ChevronLeft, ChevronRight, Download } from "lucide-react";

const MOODS = [
  { emoji: "\u{1F60A}", label: "Confident" },
  { emoji: "\u{1F610}", label: "Neutral" },
  { emoji: "\u{1F630}", label: "Anxious" },
  { emoji: "\u{1F624}", label: "Frustrated" },
];

function getStorageKey(date) {
  return `flinttrade_journal_${date}`;
}

function loadEntry(date) {
  try {
    const raw = localStorage.getItem(getStorageKey(date));
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function saveEntry(date, entry) {
  localStorage.setItem(getStorageKey(date), JSON.stringify(entry));
}

function getDaysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfMonth(year, month) {
  return new Date(year, month, 1).getDay();
}

function formatDate(y, m, d) {
  return `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export default function TradeJournal() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth());
  const [selectedDate, setSelectedDate] = useState(null);
  const [entry, setEntry] = useState(null);

  const daysInMonth = getDaysInMonth(year, month);
  const firstDay = getFirstDayOfMonth(year, month);
  const monthName = new Date(year, month).toLocaleString("en-IN", { month: "long", year: "numeric" });

  const calendarDays = useMemo(() => {
    const days = [];
    for (let i = 0; i < firstDay; i++) days.push(null);
    for (let d = 1; d <= daysInMonth; d++) days.push(d);
    return days;
  }, [firstDay, daysInMonth]);

  const prevMonth = () => {
    if (month === 0) { setMonth(11); setYear(year - 1); }
    else setMonth(month - 1);
  };
  const nextMonth = () => {
    if (month === 11) { setMonth(0); setYear(year + 1); }
    else setMonth(month + 1);
  };

  const openDay = (day) => {
    const date = formatDate(year, month, day);
    setSelectedDate(date);
    const existing = loadEntry(date);
    setEntry(existing || {
      date,
      pnl: 0,
      tradeCount: 0,
      wins: 0,
      losses: 0,
      mood: "",
      preMarket: "",
      postMarket: "",
      annotations: [],
    });
  };

  const updateEntry = (field, value) => {
    const updated = { ...entry, [field]: value };
    setEntry(updated);
    saveEntry(selectedDate, updated);
  };

  const getDayColor = (day) => {
    const date = formatDate(year, month, day);
    const e = loadEntry(date);
    if (!e) return "bg-gray-800 text-gray-400 hover:bg-gray-700";
    if (e.pnl > 0) return "bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30";
    if (e.pnl < 0) return "bg-red-500/20 text-red-400 hover:bg-red-500/30";
    return "bg-gray-700 text-gray-300 hover:bg-gray-600";
  };

  // Monthly summary
  const monthlySummary = useMemo(() => {
    let totalPnl = 0;
    let tradingDays = 0;
    let bestDay = { date: "", pnl: -Infinity };
    let worstDay = { date: "", pnl: Infinity };
    const moodCount = {};

    for (let d = 1; d <= daysInMonth; d++) {
      const date = formatDate(year, month, d);
      const e = loadEntry(date);
      if (e) {
        tradingDays++;
        totalPnl += e.pnl || 0;
        if ((e.pnl || 0) > bestDay.pnl) bestDay = { date, pnl: e.pnl || 0 };
        if ((e.pnl || 0) < worstDay.pnl) worstDay = { date, pnl: e.pnl || 0 };
        if (e.mood) moodCount[e.mood] = (moodCount[e.mood] || 0) + 1;
      }
    }

    const topMood = Object.entries(moodCount).sort((a, b) => b[1] - a[1])[0];
    return {
      totalPnl,
      tradingDays,
      avgDaily: tradingDays > 0 ? totalPnl / tradingDays : 0,
      bestDay: bestDay.pnl > -Infinity ? bestDay : null,
      worstDay: worstDay.pnl < Infinity ? worstDay : null,
      topMood: topMood ? topMood[0] : "—",
    };
  }, [year, month, daysInMonth]);

  const exportCSV = () => {
    const rows = [["Date", "P&L", "Trades", "Wins", "Losses", "Mood", "Pre-Market Notes", "Post-Market Notes"]];
    for (let d = 1; d <= daysInMonth; d++) {
      const date = formatDate(year, month, d);
      const e = loadEntry(date);
      if (e) {
        rows.push([e.date, e.pnl, e.tradeCount, e.wins, e.losses, e.mood, `"${(e.preMarket || "").replace(/"/g, '""')}"`, `"${(e.postMarket || "").replace(/"/g, '""')}"`]);
      }
    }
    const csv = rows.map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `journal_${year}_${String(month + 1).padStart(2, "0")}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="grid grid-cols-3 gap-4 h-full">
      {/* Left: Calendar + Summary */}
      <div className="col-span-1 space-y-4">
        {/* Calendar */}
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="flex items-center justify-between mb-3">
            <button onClick={prevMonth} className="p-1 hover:bg-gray-800 rounded"><ChevronLeft size={16} /></button>
            <span className="text-sm font-semibold">{monthName}</span>
            <button onClick={nextMonth} className="p-1 hover:bg-gray-800 rounded"><ChevronRight size={16} /></button>
          </div>
          <div className="grid grid-cols-7 gap-1 text-center text-[10px] text-gray-500 mb-1">
            {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => <div key={i}>{d}</div>)}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {calendarDays.map((day, i) => (
              <div key={i}>
                {day ? (
                  <button
                    onClick={() => openDay(day)}
                    className={`w-full aspect-square rounded text-xs font-mono flex items-center justify-center ${
                      selectedDate === formatDate(year, month, day) ? "ring-2 ring-emerald-500" : ""
                    } ${getDayColor(day)}`}
                  >
                    {day}
                  </button>
                ) : <div />}
              </div>
            ))}
          </div>
        </div>

        {/* Monthly summary */}
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-gray-400">Monthly Summary</h3>
            <button onClick={exportCSV} className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-200">
              <Download size={12} /> CSV
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <div className="text-[10px] text-gray-500">Total P&L</div>
              <div className={`font-mono font-bold ${monthlySummary.totalPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                ₹{monthlySummary.totalPnl >= 0 ? "+" : ""}{monthlySummary.totalPnl.toLocaleString("en-IN")}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-gray-500">Avg Daily P&L</div>
              <div className="font-mono">₹{Math.round(monthlySummary.avgDaily).toLocaleString("en-IN")}</div>
            </div>
            <div>
              <div className="text-[10px] text-gray-500">Trading Days</div>
              <div className="font-mono">{monthlySummary.tradingDays}</div>
            </div>
            <div>
              <div className="text-[10px] text-gray-500">Top Mood</div>
              <div>{monthlySummary.topMood}</div>
            </div>
            {monthlySummary.bestDay && (
              <div>
                <div className="text-[10px] text-gray-500">Best Day</div>
                <div className="font-mono text-emerald-400">+₹{monthlySummary.bestDay.pnl.toLocaleString("en-IN")}</div>
              </div>
            )}
            {monthlySummary.worstDay && (
              <div>
                <div className="text-[10px] text-gray-500">Worst Day</div>
                <div className="font-mono text-red-400">₹{monthlySummary.worstDay.pnl.toLocaleString("en-IN")}</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Right: Journal entry */}
      <div className="col-span-2">
        {entry ? (
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">{entry.date}</h2>
              <div className="flex items-center gap-3 text-xs text-gray-400">
                <span>P&L: <strong className={entry.pnl >= 0 ? "text-emerald-400" : "text-red-400"}>₹{entry.pnl >= 0 ? "+" : ""}{(entry.pnl || 0).toLocaleString("en-IN")}</strong></span>
                <span>Trades: <strong className="text-gray-200">{entry.tradeCount || 0}</strong></span>
                <span>W/L: <strong className="text-emerald-400">{entry.wins || 0}</strong>/<strong className="text-red-400">{entry.losses || 0}</strong></span>
              </div>
            </div>

            {/* P&L and trade count inputs */}
            <div className="grid grid-cols-4 gap-2">
              <div>
                <label className="block text-[10px] text-gray-500 mb-1">P&L (₹)</label>
                <input type="number" value={entry.pnl || ""} onChange={(e) => updateEntry("pnl", Number(e.target.value) || 0)}
                  className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs font-mono" />
              </div>
              <div>
                <label className="block text-[10px] text-gray-500 mb-1">Total Trades</label>
                <input type="number" value={entry.tradeCount || ""} onChange={(e) => updateEntry("tradeCount", Number(e.target.value) || 0)}
                  className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs font-mono" />
              </div>
              <div>
                <label className="block text-[10px] text-gray-500 mb-1">Wins</label>
                <input type="number" value={entry.wins || ""} onChange={(e) => updateEntry("wins", Number(e.target.value) || 0)}
                  className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs font-mono" />
              </div>
              <div>
                <label className="block text-[10px] text-gray-500 mb-1">Losses</label>
                <input type="number" value={entry.losses || ""} onChange={(e) => updateEntry("losses", Number(e.target.value) || 0)}
                  className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs font-mono" />
              </div>
            </div>

            {/* Mood */}
            <div>
              <label className="block text-[10px] text-gray-500 mb-1">Mood</label>
              <div className="flex gap-2">
                {MOODS.map((m) => (
                  <button key={m.label} onClick={() => updateEntry("mood", m.label)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs ${
                      entry.mood === m.label ? "bg-emerald-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"
                    }`}>
                    <span className="text-base">{m.emoji}</span> {m.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Notes */}
            <div>
              <label className="block text-[10px] text-gray-500 mb-1">Pre-Market Notes (plan for the day)</label>
              <textarea value={entry.preMarket || ""} onChange={(e) => updateEntry("preMarket", e.target.value)}
                rows={3} className="w-full bg-gray-800 rounded px-3 py-2 text-xs resize-none" placeholder="What's the plan today?" />
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 mb-1">Post-Market Notes (what happened, lessons)</label>
              <textarea value={entry.postMarket || ""} onChange={(e) => updateEntry("postMarket", e.target.value)}
                rows={3} className="w-full bg-gray-800 rounded px-3 py-2 text-xs resize-none" placeholder="What happened today? Lessons learned?" />
            </div>

            {/* Trade annotations */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[10px] text-gray-500">Trade Annotations</label>
                <button onClick={() => updateEntry("annotations", [...(entry.annotations || []), { symbol: "", note: "" }])}
                  className="text-[10px] text-emerald-400 hover:text-emerald-300">+ Add trade</button>
              </div>
              <div className="space-y-2">
                {(entry.annotations || []).map((ann, i) => (
                  <div key={i} className="flex gap-2">
                    <input value={ann.symbol} placeholder="Symbol"
                      onChange={(e) => {
                        const updated = [...entry.annotations];
                        updated[i] = { ...updated[i], symbol: e.target.value };
                        updateEntry("annotations", updated);
                      }}
                      className="w-28 bg-gray-800 rounded px-2 py-1.5 text-xs" />
                    <input value={ann.note} placeholder="Notes — why entered, what went wrong, lessons"
                      onChange={(e) => {
                        const updated = [...entry.annotations];
                        updated[i] = { ...updated[i], note: e.target.value };
                        updateEntry("annotations", updated);
                      }}
                      className="flex-1 bg-gray-800 rounded px-2 py-1.5 text-xs" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">
            Select a day from the calendar to view or create a journal entry
          </div>
        )}
      </div>
    </div>
  );
}
