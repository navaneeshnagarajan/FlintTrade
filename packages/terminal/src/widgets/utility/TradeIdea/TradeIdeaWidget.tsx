/**
 * TradeIdeaWidget — Create, save, and track trade ideas/setups.
 *
 * Form: symbol, direction, entry zone, SL, target, timeframe, notes, tags
 * Saved as cards with status (planned/active/completed/expired)
 * Persisted to localStorage under key `flinttrade:tradeideas`
 */

import { useState, useEffect, useCallback, memo } from "react";
import { Lightbulb, Plus, X, Check, ChevronDown, ChevronUp, Tag } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Direction = "bullish" | "bearish" | "neutral";
type IdeaStatus = "planned" | "active" | "completed" | "expired";
type Timeframe = "intraday" | "swing" | "positional" | "investment";

export interface TradeIdea {
  id: string;
  symbol: string;
  direction: Direction;
  entryZone: string;
  stopLoss: string;
  target: string;
  timeframe: Timeframe;
  notes: string;
  tags: string[];
  status: IdeaStatus;
  createdAt: string;
}

// ---------------------------------------------------------------------------
// Constants & helpers
// ---------------------------------------------------------------------------

const STORAGE_KEY = "flinttrade:tradeideas";
const ALL_STATUSES: IdeaStatus[] = ["planned", "active", "completed", "expired"];
const DIRECTIONS: Direction[] = ["bullish", "bearish", "neutral"];
const TIMEFRAMES: Timeframe[] = ["intraday", "swing", "positional", "investment"];

const STATUS_COLOUR: Record<IdeaStatus, string> = {
  planned:   "text-accent",
  active:    "text-warning",
  completed: "text-profit",
  expired:   "text-text-muted",
};

const DIR_COLOUR: Record<Direction, string> = {
  bullish: "text-profit",
  bearish: "text-loss",
  neutral: "text-text-muted",
};

function loadIdeas(): TradeIdea[] {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]") as TradeIdea[]; }
  catch { return []; }
}

function saveIdeas(ideas: TradeIdea[]): void {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(ideas)); } catch { /* quota */ }
}

// ---------------------------------------------------------------------------
// Idea card
// ---------------------------------------------------------------------------

function IdeaCard({ idea, onStatus, onDelete }: {
  idea: TradeIdea;
  onStatus: (id: string, s: IdeaStatus) => void;
  onDelete: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <article className="bg-surface-card rounded border border-border-default overflow-hidden"
      aria-label={`Trade idea: ${idea.symbol} ${idea.direction}`}>
      <div className="flex items-center gap-2 px-2.5 py-2">
        <span className="text-xs font-bold text-text-primary">{idea.symbol}</span>
        <span className={cn("text-xxs font-medium capitalize", DIR_COLOUR[idea.direction])}>{idea.direction}</span>
        <span className="text-xxs text-text-muted">{idea.timeframe}</span>
        <div className="flex-1" />
        <span className={cn("text-xxs capitalize px-1.5 py-0.5 rounded border border-border-subtle", STATUS_COLOUR[idea.status])}>{idea.status}</span>
        <button onClick={() => setOpen((e) => !e)} className="p-0.5 rounded text-text-muted hover:text-text-primary"
          aria-label={open ? "Collapse" : "Expand"}>
          {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
        <button onClick={() => onDelete(idea.id)} className="p-0.5 rounded text-text-muted hover:text-loss"
          aria-label={`Delete idea for ${idea.symbol}`}>
          <X size={12} />
        </button>
      </div>
      <div className="flex gap-3 px-2.5 pb-2 text-xxs font-mono">
        <span className="text-text-muted">Entry <span className="text-text-primary">{idea.entryZone || "—"}</span></span>
        <span className="text-text-muted">SL <span className="text-loss">{idea.stopLoss || "—"}</span></span>
        <span className="text-text-muted">Tgt <span className="text-profit">{idea.target || "—"}</span></span>
      </div>
      {open && (
        <div className="border-t border-border-subtle px-2.5 py-2 space-y-2">
          {idea.notes && <p className="text-xxs text-text-secondary">{idea.notes}</p>}
          {idea.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {idea.tags.map((t) => (
                <span key={t} className="flex items-center gap-0.5 px-1.5 py-0.5 text-xxs bg-surface-hover rounded text-text-muted">
                  <Tag size={9} aria-hidden="true" />{t}
                </span>
              ))}
            </div>
          )}
          <div className="flex gap-1 flex-wrap" role="group" aria-label="Change status">
            {ALL_STATUSES.filter((s) => s !== idea.status).map((s) => (
              <button key={s} onClick={() => onStatus(idea.id, s)}
                className="px-2 py-0.5 text-xxs border border-border-default rounded hover:bg-surface-hover text-text-muted capitalize transition-colors">
                Mark {s}
              </button>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}

// ---------------------------------------------------------------------------
// Add form
// ---------------------------------------------------------------------------

function AddForm({ onAdd, onCancel }: { onAdd: (idea: TradeIdea) => void; onCancel: () => void }) {
  const [sym, setSym] = useState("");
  const [dir, setDir] = useState<Direction>("bullish");
  const [entry, setEntry] = useState("");
  const [sl, setSl] = useState("");
  const [tgt, setTgt] = useState("");
  const [tf, setTf] = useState<Timeframe>("intraday");
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");

  const submit = () => {
    const symbol = sym.trim().toUpperCase();
    if (!symbol) return;
    onAdd({
      id: `idea_${Date.now()}`,
      symbol, direction: dir, entryZone: entry.trim(), stopLoss: sl.trim(),
      target: tgt.trim(), timeframe: tf, notes: notes.trim(),
      tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
      status: "planned", createdAt: new Date().toISOString(),
    });
  };

  const inCls = "w-full px-2 py-1 text-xs bg-surface-hover border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/50 font-mono";
  const pillCls = (active: boolean) => cn("px-2 py-1 text-xxs rounded border capitalize transition-colors",
    active ? "bg-accent/15 border-accent/40 text-accent" : "border-border-default text-text-muted hover:bg-surface-hover");

  return (
    <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="space-y-2 p-2.5 bg-surface-elevated border border-border-default rounded"
      aria-label="Add trade idea form">
      <div className="flex gap-2">
        <input id="ti-symbol" value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())}
          placeholder="NIFTY" className={cn(inCls, "flex-1")} aria-label="Symbol" />
        <div className="flex gap-1" role="group" aria-label="Direction">
          {DIRECTIONS.map((d) => <button key={d} type="button" onClick={() => setDir(d)} className={pillCls(dir === d)}>{d}</button>)}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <input value={entry} onChange={(e) => setEntry(e.target.value)} placeholder="Entry" className={inCls} aria-label="Entry Zone" />
        <input value={sl} onChange={(e) => setSl(e.target.value)} placeholder="Stop Loss" className={inCls} aria-label="Stop Loss" />
        <input value={tgt} onChange={(e) => setTgt(e.target.value)} placeholder="Target" className={inCls} aria-label="Target" />
      </div>
      <div className="flex gap-1" role="group" aria-label="Timeframe">
        {TIMEFRAMES.map((t) => <button key={t} type="button" onClick={() => setTf(t)} className={pillCls(tf === t)}>{t}</button>)}
      </div>
      <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes…" rows={2}
        className="w-full px-2 py-1 text-xs bg-surface-hover border border-border-default rounded resize-none text-text-primary focus:outline-none focus:border-accent/50"
        aria-label="Notes" id="ti-notes" />
      <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="Tags (comma-separated)"
        className={inCls} aria-label="Tags" />
      <div className="flex gap-2">
        <button type="submit" className="flex-1 flex items-center justify-center gap-1 h-7 text-xs bg-accent text-white rounded hover:bg-accent/80 transition-colors">
          <Check size={11} aria-hidden="true" />Save Idea
        </button>
        <button type="button" onClick={onCancel} className="h-7 px-3 text-xs border border-border-default rounded hover:bg-surface-hover text-text-muted transition-colors">
          Cancel
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function TradeIdeaWidget() {
  const track = useTrackBehavior();
  const [ideas, setIdeas] = useState<TradeIdea[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [filter, setFilter] = useState<IdeaStatus | "all">("all");

  useEffect(() => { setIdeas(loadIdeas()); track("trade", "widget_view_tradeidea"); }, [track]);

  const handleAdd = useCallback((idea: TradeIdea) => {
    setIdeas((p) => { const u = [idea, ...p]; saveIdeas(u); return u; });
    setShowForm(false);
  }, []);

  const handleStatus = useCallback((id: string, status: IdeaStatus) => {
    setIdeas((p) => { const u = p.map((i) => i.id === id ? { ...i, status } : i); saveIdeas(u); return u; });
  }, []);

  const handleDelete = useCallback((id: string) => {
    setIdeas((p) => { const u = p.filter((i) => i.id !== id); saveIdeas(u); return u; });
  }, []);

  const filtered = filter === "all" ? ideas : ideas.filter((i) => i.status === filter);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Trade Idea widget">
      <div className="flex-none flex items-center gap-2 px-2.5 py-1.5 bg-surface-card border-b border-border-default">
        <Lightbulb size={13} className="text-warning shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Trade Ideas</span>
        <span className="px-1.5 py-0.5 text-xxs bg-surface-hover rounded text-text-muted font-mono">{ideas.length}</span>
        <div className="flex-1" />
        <button onClick={() => setShowForm((s) => !s)}
          className="flex items-center gap-1 px-2 py-1 text-xxs font-medium bg-accent/15 text-accent border border-accent/30 rounded hover:bg-accent/25 transition-colors"
          aria-label="Add new trade idea" aria-expanded={showForm}>
          <Plus size={11} aria-hidden="true" />New
        </button>
      </div>

      <div className="flex-none flex items-center gap-px px-2.5 py-1.5 border-b border-border-subtle overflow-x-auto"
        role="tablist" aria-label="Filter by status">
        {(["all", ...ALL_STATUSES] as const).map((s) => (
          <button key={s} role="tab" aria-selected={filter === s} onClick={() => setFilter(s)}
            className={cn("px-2 py-0.5 text-xxs font-medium rounded capitalize transition-colors whitespace-nowrap",
              filter === s ? "bg-accent/15 text-accent" : "text-text-muted hover:text-text-primary hover:bg-surface-hover")}>
            {s === "all" ? `All (${ideas.length})` : `${s} (${ideas.filter((i) => i.status === s).length})`}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-2">
        {showForm && <AddForm onAdd={handleAdd} onCancel={() => setShowForm(false)} />}
        {filtered.length === 0 && !showForm && (
          <div className="flex flex-col items-center justify-center h-24 text-text-muted gap-1">
            <Lightbulb size={20} aria-hidden="true" />
            <span className="text-xs">No trade ideas yet</span>
            <span className="text-xxs text-text-muted">Click New to create one</span>
          </div>
        )}
        {filtered.map((idea) => (
          <IdeaCard key={idea.id} idea={idea} onStatus={handleStatus} onDelete={handleDelete} />
        ))}
      </div>
    </div>
  );
}

export default memo(TradeIdeaWidget);
