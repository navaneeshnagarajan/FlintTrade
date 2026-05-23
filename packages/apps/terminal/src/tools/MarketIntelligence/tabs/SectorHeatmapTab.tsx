import { useState, useMemo } from "react";
import { Map as MapIcon } from "lucide-react";
import { INDIA_SECTORS } from "../data";
import { DataNotice, TfButton } from "../shared";
import { formatReturn, getReturnValue, getThemeColor } from "../utils";
import { TIMEFRAMES } from "../types";
import type { TF } from "../types";

export function SectorHeatmapTab() {
  const [selectedTf, setSelectedTf] = useState<TF>("1D");

  function getCellColor(v: number | null): string {
    if (v === null) return getThemeColor("--color-card", "#16161f");
    if (v >= 3) return "#064e3b";
    if (v >= 1.5) return "#065f46";
    if (v >= 0.5) return "#047857";
    if (v >= 0) return "#059669";
    if (v >= -0.5) return "#991b1b";
    if (v >= -1.5) return "#7f1d1d";
    if (v >= -3) return "#6b1212";
    return "#450a0a";
  }

  function getTextColor(v: number | null): string {
    if (v === null) return "#6b6b8a";
    return v >= 0 ? "#a7f3d0" : "#fca5a5";
  }

  const sorted = useMemo(
    () => [...INDIA_SECTORS].sort((a, b) => b.market_cap_cr - a.market_cap_cr),
    []
  );

  const totalCap = sorted.reduce((a, b) => a + b.market_cap_cr, 0);

  return (
    <div className="p-4">
      <DataNotice />
      <div className="flex items-center gap-1.5 mb-4">
        {TIMEFRAMES.map((tf) => (
          <TfButton key={tf} tf={tf} active={selectedTf === tf} onClick={() => setSelectedTf(tf)} />
        ))}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {sorted.map((sector) => {
          const ret = getReturnValue(sector, selectedTf);
          const capWeight = (sector.market_cap_cr / totalCap) * 100;
          const widthPct = Math.max(12, Math.min(28, capWeight * 0.8));
          const heightPx = capWeight >= 10 ? 84 : capWeight >= 6 ? 72 : 62;

          return (
            <div
              key={sector.ticker}
              className="rounded-md flex flex-col justify-between p-2.5 cursor-default transition-opacity hover:opacity-90 shrink-0"
              style={{
                backgroundColor: getCellColor(ret),
                width: `calc(${widthPct}% - 6px)`,
                height: `${heightPx}px`,
              }}
              title={`${sector.name}: ${formatReturn(ret)}`}
            >
              <div className="text-xs text-white/75 leading-tight font-medium truncate">
                {sector.name}
              </div>
              <div className="flex items-end justify-between gap-1">
                <div
                  className="text-sm font-mono font-bold"
                  style={{ color: getTextColor(ret) }}
                >
                  {formatReturn(ret)}
                </div>
                <div className="text-xxs text-white/40 font-mono">
                  {(sector.market_cap_cr / 100000).toFixed(1)}L Cr
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-3 mt-4 text-xs text-text-muted">
        <MapIcon size={10} />
        <span>Cell size = market cap weight</span>
        <span className="ml-1">Color:</span>
        {[
          { label: ">3%", color: "#064e3b" },
          { label: "1.5-3%", color: "#065f46" },
          { label: "0-1.5%", color: "#059669" },
          { label: "0 to -1.5%", color: "#991b1b" },
          { label: "<-3%", color: "#450a0a" },
        ].map((l) => (
          <div key={l.label} className="flex items-center gap-1">
            <span className="w-3 h-3 rounded" style={{ backgroundColor: l.color }} />
            <span>{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
