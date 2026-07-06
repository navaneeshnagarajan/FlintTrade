/**
 * TimeSalesWidget — Time & Sales tape (W3).
 *
 * Streams inferred trade prints for the selected instrument: the OpenAlgo
 * WebSocket carries quote ticks (LTP + cumulative volume), not per-trade data,
 * so each print is derived from a tick (size = volume delta, aggressor side by
 * the tick rule) and the header says so honestly. Follows the workspace's
 * selected symbol (watchlist click) with a local selector fallback; sample tape
 * + preview teaser when disconnected.
 */

import { memo, useMemo, useState } from "react";
import { useAtomValue } from "jotai";
import { ChevronDown, ClipboardList } from "lucide-react";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import { useTape } from "./useTape";
import { SAMPLE_TAPE } from "./sampleData";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import type { TapePrint, TapeSide } from "./tape";
import type { WsInstrument } from "@/types/api";

const FALLBACK_SYMBOLS: WsInstrument[] = [
  { symbol: "RELIANCE", exchange: "NSE" },
  { symbol: "TCS", exchange: "NSE" },
  { symbol: "HDFCBANK", exchange: "NSE" },
  { symbol: "SBIN", exchange: "NSE" },
  { symbol: "NIFTY", exchange: "NSE_INDEX" },
];

const PRICE_FMT = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const QTY_FMT = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function sideCls(side: TapeSide): string {
  if (side === "buy") return "text-green-500";
  if (side === "sell") return "text-red-500";
  return "text-text-muted";
}

function PrintRow({ p }: { p: TapePrint }) {
  return (
    <tr className="border-b border-border-default/40 last:border-0">
      <td className="py-0.5 pr-2 font-mono tabular-nums text-text-muted">{p.time}</td>
      <td className={`py-0.5 px-2 text-right font-mono tabular-nums ${sideCls(p.side)}`}>
        {PRICE_FMT.format(p.price)}
      </td>
      <td className="py-0.5 px-2 text-right font-mono tabular-nums text-text-primary">
        {p.qty > 0 ? QTY_FMT.format(p.qty) : "—"}
      </td>
      <td className={`py-0.5 pl-2 uppercase text-[10px] font-semibold ${sideCls(p.side)}`}>
        {p.side === "neutral" ? "—" : p.side}
      </td>
    </tr>
  );
}

function Selector({ value, options, onChange }: { value: string; options: string[]; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors min-w-20"
      >
        <span className="flex-1 text-left">{value}</span>
        <ChevronDown size={10} className={`transition-transform flex-none ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute top-full right-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full max-h-48 overflow-y-auto">
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => { onChange(opt); setOpen(false); }}
              className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${opt === value ? "text-accent" : "text-text-primary"}`}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function TimeSalesWidget() {
  const isConnected = useBrokerConnected();
  const selected = useAtomValue(selectedSymbolAtom);
  const [manual, setManual] = useState<WsInstrument | null>(null);

  // Workspace selection wins unless the user picked one locally after that.
  const instrument = manual ?? selected ?? FALLBACK_SYMBOLS[0];

  const liveTape = useTape(instrument, isConnected);
  const tape = isConnected ? liveTape : SAMPLE_TAPE;
  const isSample = !isConnected;

  const buyQty = useMemo(() => tape.filter((p) => p.side === "buy").reduce((s, p) => s + p.qty, 0), [tape]);
  const sellQty = useMemo(() => tape.filter((p) => p.side === "sell").reduce((s, p) => s + p.qty, 0), [tape]);
  const total = buyQty + sellQty;
  const buyPct = total > 0 ? (buyQty / total) * 100 : 50;

  const content = (
    <div className="flex flex-col h-full gap-2 p-3 text-xs">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-1.5">
            <ClipboardList size={14} /> Time &amp; Sales
          </h3>
          <p className="text-[10px] text-text-muted">
            {instrument.symbol} · prints inferred from quote ticks (tick rule)
            {isSample && <span className="ml-1 text-amber-500">· Demo data</span>}
          </p>
        </div>
        <Selector
          value={instrument.symbol}
          options={FALLBACK_SYMBOLS.map((s) => s.symbol)}
          onChange={(sym) => setManual(FALLBACK_SYMBOLS.find((s) => s.symbol === sym) ?? null)}
        />
      </div>

      {/* Buy/sell pressure bar over the visible tape */}
      <div>
        <div className="relative h-1.5 rounded-full bg-red-500/25 overflow-hidden">
          <div className="h-full bg-green-500/70" style={{ width: `${buyPct}%` }} />
        </div>
        <div className="flex justify-between mt-0.5 text-[10px] text-text-muted font-mono tabular-nums">
          <span className="text-green-500">B {QTY_FMT.format(buyQty)}</span>
          <span className="text-red-500">S {QTY_FMT.format(sellQty)}</span>
        </div>
      </div>

      {tape.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted text-center">
          {isConnected ? "Waiting for ticks…" : "No prints"}
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-surface-card">
              <tr className="text-[10px] uppercase tracking-wide text-text-muted border-b border-border-default">
                <th className="py-1 pr-2 text-left font-medium">Time</th>
                <th className="py-1 px-2 text-right font-medium">Price</th>
                <th className="py-1 px-2 text-right font-medium">Qty</th>
                <th className="py-1 pl-2 text-left font-medium">Side</th>
              </tr>
            </thead>
            <tbody>
              {tape.map((p) => (
                <PrintRow key={p.id} p={p} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  return isConnected ? (
    content
  ) : (
    <FeatureTeaser status="preview" featureName="Time & Sales" version={APP_VERSION_TAG}>
      {content}
    </FeatureTeaser>
  );
}

export default memo(TimeSalesWidget);
