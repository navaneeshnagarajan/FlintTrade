/**
 * WatchlistCard — Top 5 index symbols with live prices from Jotai atoms.
 */

import { useAtomValue } from "jotai";
import { BentoCard } from "@/components/bento/BentoCard";
import {
  niftyAtom,
  bankniftyAtom,
  sensexAtom,
  vixAtom,
  goldAtom,
} from "@/atoms/marketAtoms";

interface WatchlistRow {
  label: string;
  value: number | null;
  change: number | null;
}

function WatchlistRow({ label, value, change }: WatchlistRow) {
  const positive = (change ?? 0) >= 0;
  return (
    <div className="flex items-center justify-between py-1.5 px-2 rounded-[8px] hover:bg-[rgba(255,255,255,0.03)] transition-colors">
      <span className="text-xs font-medium text-[#9090b0]">{label}</span>
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs text-[#e8e8f0]">
          {value != null ? value.toLocaleString("en-IN") : "—"}
        </span>
        {change != null && (
          <span
            className="font-mono text-[10px]"
            style={{ color: positive ? "#22c55e" : "#ef4444" }}
          >
            {positive ? "+" : ""}{change.toFixed(2)}%
          </span>
        )}
      </div>
    </div>
  );
}

export function WatchlistCard() {
  const nifty    = useAtomValue(niftyAtom);
  const bankNifty = useAtomValue(bankniftyAtom);
  const sensex   = useAtomValue(sensexAtom);
  const vix      = useAtomValue(vixAtom);
  const gold     = useAtomValue(goldAtom);

  const rows: WatchlistRow[] = [
    { label: "NIFTY 50",  value: nifty?.ltp ?? null,     change: nifty?.pct ?? null },
    { label: "BANK NIFTY",value: bankNifty?.ltp ?? null, change: bankNifty?.pct ?? null },
    { label: "SENSEX",    value: sensex?.ltp ?? null,    change: sensex?.pct ?? null },
    { label: "VIX",       value: vix?.ltp ?? null,       change: vix?.pct ?? null },
    { label: "GOLD",      value: gold?.ltp ?? null,      change: gold?.pct ?? null },
  ];

  return (
    <BentoCard size="default" label="Watchlist" data-testid="watchlist-card">
      <div className="p-4 h-full flex flex-col gap-2">
        <p className="text-[10px] font-medium uppercase tracking-widest text-[#505068]">
          Watchlist
        </p>
        <div className="flex-1 space-y-0.5">
          {rows.map((row) => (
            <WatchlistRow key={row.label} {...row} />
          ))}
        </div>
      </div>
    </BentoCard>
  );
}
