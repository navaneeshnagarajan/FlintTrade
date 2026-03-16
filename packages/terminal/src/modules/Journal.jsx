import { useState } from "react";
import { Download, Plus } from "lucide-react";

const MOODS = [
  { label: "Confident", emoji: "💪", color: "bg-emerald-500/20 text-emerald-400" },
  { label: "Neutral", emoji: "😐", color: "bg-gray-500/20 text-gray-400" },
  { label: "Anxious", emoji: "😰", color: "bg-yellow-500/20 text-yellow-400" },
  { label: "Frustrated", emoji: "😤", color: "bg-red-500/20 text-red-400" },
];

function CalendarGrid({ entries }) {
  const today = new Date();
  const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  const firstDay = new Date(today.getFullYear(), today.getMonth(), 1).getDay();
  const entryMap = {};
  for (const e of entries) {
    const d = parseInt(e.date.split("-")[2], 10);
    entryMap[d] = e.pnl;
  }

  return (
    <div className="grid grid-cols-7 gap-1 text-[10px]">
      {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((d) => (
        <div key={d} className="text-center text-gray-600 py-1">{d}</div>
      ))}
      {Array.from({ length: firstDay }, (_, i) => <div key={`e${i}`} />)}
      {Array.from({ length: daysInMonth }, (_, i) => {
        const day = i + 1;
        const pnl = entryMap[day];
        let bg = "bg-gray-800/50";
        if (pnl !== undefined) bg = pnl >= 0 ? "bg-emerald-500/20" : "bg-red-500/20";
        return (
          <div key={day} className={`text-center py-1.5 rounded ${bg} ${day === today.getDate() ? "ring-1 ring-emerald-500" : ""}`}>
            {day}
          </div>
        );
      })}
    </div>
  );
}

export default function Journal() {
  // Journal entries are stored locally — no mock data.
  const [entries, setEntries] = useState([]);
  const [newNote, setNewNote] = useState("");
  const [newMood, setNewMood] = useState(1);

  const addEntry = () => {
    const today = new Date().toISOString().slice(0, 10);
    if (entries.some((e) => e.date === today)) return;
    setEntries([{ date: today, mood: newMood, pnl: 0, notes: newNote }, ...entries]);
    setNewNote("");
  };

  const winDays = entries.filter((e) => e.pnl > 0).length;
  const lossDays = entries.filter((e) => e.pnl < 0).length;

  const exportCSV = () => {
    const rows = entries.map((e) => `${e.date},${MOODS[e.mood]?.label || ""},${e.pnl},"${e.notes}"`);
    const csv = "Date,Mood,P&L,Notes\n" + rows.join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "journal.csv";
    a.click();
  };

  return (
    <div className="grid grid-cols-3 gap-4 h-full">
      {/* Journal entries */}
      <div className="col-span-2 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm text-gray-500 uppercase tracking-wide">Trade Journal</h2>
          {entries.length > 0 && (
            <button onClick={exportCSV} className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 px-2 py-1 transition-colors">
              <Download size={12} /> Export
            </button>
          )}
        </div>

        {/* New entry form */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Today's mood:</span>
            {MOODS.map((m, i) => (
              <button key={i} onClick={() => setNewMood(i)}
                className={`text-lg px-1 rounded ${newMood === i ? "ring-2 ring-emerald-500" : "opacity-50 hover:opacity-100"}`}>
                {m.emoji}
              </button>
            ))}
          </div>
          <textarea value={newNote} onChange={(e) => setNewNote(e.target.value)}
            placeholder="What happened today? Lessons learned..."
            className="w-full bg-gray-800 rounded-lg px-3 py-2 text-xs text-gray-100 placeholder-gray-600 resize-none h-16" />
          <button onClick={addEntry} className="flex items-center gap-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-lg transition-colors">
            <Plus size={12} /> Save Entry
          </button>
        </div>

        {/* Entries list */}
        <div className="flex-1 overflow-auto space-y-2">
          {entries.length === 0 ? (
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-10 text-center">
              <p className="text-gray-600 text-sm">No journal entries yet</p>
              <p className="text-gray-700 text-xs mt-1">Record your trading day above to build your journal</p>
            </div>
          ) : entries.map((e) => {
            const mood = MOODS[e.mood] || MOODS[1];
            return (
              <div key={e.date} className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-600 font-mono">{e.date}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${mood.color}`}>{mood.emoji} {mood.label}</span>
                  </div>
                  <span className={`text-sm font-mono font-bold ${e.pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {e.pnl >= 0 ? "+" : ""}{e.pnl.toLocaleString("en-IN")}
                  </span>
                </div>
                <p className="text-xs text-gray-400">{e.notes}</p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Sidebar: calendar + streaks */}
      <div className="space-y-3">
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wide mb-3">Calendar</div>
          <CalendarGrid entries={entries} />
        </div>
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wide mb-3">Streaks</div>
          <div className="flex gap-6 text-xs">
            <div>
              <div className="text-emerald-400 font-bold text-lg font-mono">{winDays}</div>
              <div className="text-gray-600">Win days</div>
            </div>
            <div>
              <div className="text-red-400 font-bold text-lg font-mono">{lossDays}</div>
              <div className="text-gray-600">Loss days</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
