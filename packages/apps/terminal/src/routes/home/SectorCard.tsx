/**
 * SectorCard — 2×3 grid of sector performance badges.
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { Layers } from "lucide-react";

interface SectorItem {
  name: string;
  change: number;
}

// Placeholder data — will come from sectormap API in Phase 2
const SECTORS: SectorItem[] = [
  { name: "IT",      change:  1.24 },
  { name: "BANK",    change: -0.38 },
  { name: "PHARMA",  change:  0.67 },
  { name: "AUTO",    change: -1.02 },
  { name: "FMCG",    change:  0.15 },
  { name: "ENERGY",  change: -0.55 },
];

export function SectorCard() {
  return (
    <BentoCard size="default" label="Sector Performance" data-testid="sector-card">
      <div className="p-4 h-full flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Layers size={13} className="text-text-muted" aria-hidden="true" />
          <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
            Sectors
          </p>
        </div>

        <div className="grid grid-cols-2 gap-1.5 flex-1">
          {SECTORS.map((s) => {
            const positive = s.change >= 0;
            return (
              <div
                key={s.name}
                className="flex items-center justify-between px-2 py-1.5 rounded-[8px]"
                style={{
                  background: positive
                    ? "rgba(34,197,94,0.06)"
                    : "rgba(239,68,68,0.06)",
                  border: "1px solid",
                  borderColor: positive
                    ? "rgba(34,197,94,0.12)"
                    : "rgba(239,68,68,0.12)",
                }}
              >
                <span className="text-[10px] font-medium text-text-secondary">{s.name}</span>
                <span
                  className="font-mono text-[10px] font-semibold"
                  style={{ color: positive ? "var(--color-bullish-text)" : "var(--color-bearish-text)" }}
                >
                  {positive ? "+" : ""}{s.change.toFixed(2)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </BentoCard>
  );
}
