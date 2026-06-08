/**
 * GlobalCard — 4 global indices with country flag emoji.
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { Globe } from "lucide-react";
import { DemoBadge } from "./DemoBadge";

interface GlobalIndex {
  name: string;
  flag: string;
  value: number;
  change: number;
}

// Placeholder data — will connect to global indices API in Phase 2
const GLOBAL_INDICES: GlobalIndex[] = [
  { name: "S&P 500",  flag: "🇺🇸", value: 5234.18, change:  0.42 },
  { name: "FTSE 100", flag: "🇬🇧", value: 7842.50, change: -0.18 },
  { name: "Nikkei",   flag: "🇯🇵", value: 38462.0, change:  1.02 },
  { name: "Hang Seng",flag: "🇭🇰", value: 17321.0, change: -0.65 },
];

export function GlobalCard() {
  return (
    <BentoCard size="default" label="Global Indices (placeholder data)" data-testid="global-card">
      <DemoBadge testId="global-demo-badge" title="Placeholder world-index quotes — not live" />
      <div className="p-4 h-full flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Globe size={13} className="text-text-muted" aria-hidden="true" />
          <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
            Global
          </p>
        </div>

        <div className="flex-1 space-y-2">
          {GLOBAL_INDICES.map((idx) => {
            const positive = idx.change >= 0;
            return (
              <div
                key={idx.name}
                className="flex items-center justify-between"
              >
                <div className="flex items-center gap-1.5">
                  <span className="text-base leading-none" aria-hidden="true">
                    {idx.flag}
                  </span>
                  <span className="text-xs text-text-secondary">{idx.name}</span>
                </div>
                <div className="text-right">
                  <span className="font-mono text-xs text-text-primary">
                    {idx.value.toLocaleString("en-US")}
                  </span>
                  <span
                    className="font-mono text-[10px] ml-1.5"
                    style={{ color: positive ? "var(--color-bullish-text)" : "var(--color-bearish-text)" }}
                  >
                    {positive ? "+" : ""}{idx.change.toFixed(2)}%
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </BentoCard>
  );
}
