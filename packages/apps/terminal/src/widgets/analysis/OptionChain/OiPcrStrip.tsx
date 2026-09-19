/**
 * Compact OI profile + PCR strip for the Option Chain (FT-TRADE-012).
 *
 * Shows the selected expiry/symbol's CE/PE OI profile and PCR. Explore
 * keeps a Sample badge and never invents live OI. An empty expiry is an
 * honest empty — no zero bars, no 0.00 PCR.
 */

import { memo } from "react";
import { Badge } from "@/components/ui/badge";
import { NUM0 } from "./formatters";
import {
  buildOiPcrStripModel,
  pcrLean,
  type OiPcrStripInput,
  type OiProfileBar,
} from "./oiPcrStrip";

function pcrVariant(pcr: number): "bullish" | "bearish" | "atm" {
  const lean = pcrLean(pcr);
  if (lean === "Bullish") return "bullish";
  if (lean === "Bearish") return "bearish";
  return "atm";
}

function barHeightPct(oi: number, maxOi: number): number {
  if (oi <= 0 || maxOi <= 0) return 0;
  return Math.max(8, Math.round((oi / maxOi) * 100));
}

function profileMaxOi(bars: readonly OiProfileBar[]): number {
  return Math.max(
    0,
    ...bars.flatMap((bar) => [bar.callOi, bar.putOi].filter((oi): oi is number => oi !== null)),
  );
}

function OiProfileBars({ bars }: { bars: readonly OiProfileBar[] }) {
  const maxOi = profileMaxOi(bars);

  return (
    <div
      className="flex min-w-0 flex-1 flex-col justify-center gap-0.5"
      role="img"
      aria-label="OI profile by strike"
    >
      <div className="flex h-5 items-end gap-px" data-oi-side="ce">
        {bars.map((bar) => (
          bar.callOi === null ? (
            <span
              key={`ce-${bar.strike}`}
              data-oi-bar="ce"
              data-strike={bar.strike}
              data-oi="unavailable"
              className="w-1.5 self-stretch rounded-sm bg-transparent"
              title={`${NUM0.format(bar.strike)} CE OI unavailable`}
            />
          ) : (
            <span
              key={`ce-${bar.strike}`}
              data-oi-bar="ce"
              data-strike={bar.strike}
              data-oi={bar.callOi}
              className="w-1.5 rounded-sm bg-loss/70"
              style={{ height: `${barHeightPct(bar.callOi, maxOi)}%` }}
              title={`${NUM0.format(bar.strike)} CE ${bar.callOi}`}
            />
          )
        ))}
      </div>
      <div className="flex h-5 items-start gap-px" data-oi-side="pe">
        {bars.map((bar) => (
          bar.putOi === null ? (
            <span
              key={`pe-${bar.strike}`}
              data-oi-bar="pe"
              data-strike={bar.strike}
              data-oi="unavailable"
              className="w-1.5 self-stretch rounded-sm bg-transparent"
              title={`${NUM0.format(bar.strike)} PE OI unavailable`}
            />
          ) : (
            <span
              key={`pe-${bar.strike}`}
              data-oi-bar="pe"
              data-strike={bar.strike}
              data-oi={bar.putOi}
              className="w-1.5 rounded-sm bg-profit/70"
              style={{ height: `${barHeightPct(bar.putOi, maxOi)}%` }}
              title={`${NUM0.format(bar.strike)} PE ${bar.putOi}`}
            />
          )
        ))}
      </div>
    </div>
  );
}

function OiPcrStrip(props: OiPcrStripInput) {
  const model = buildOiPcrStripModel(props);

  return (
    <section
      data-testid="oi-pcr-strip"
      aria-label="OI profile and PCR strip"
      className="flex-none border-b border-border-default bg-surface-card px-2 py-1.5"
    >
      <div className="flex items-center gap-2">
        {model.sample && (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            data-testid="oi-pcr-sample-badge"
            aria-label="Sample — not live open interest"
            title="Sample data — fabricated sample values, not live open interest."
          >
            Sample
          </span>
        )}
        <span className="text-xs font-medium uppercase tracking-wide text-text-muted">
          OI profile
        </span>
        <span className="font-mono text-xs text-text-secondary">
          {model.symbol}
          {model.expiry ? ` · ${model.expiry}` : ""}
        </span>

        {model.kind === "profile" ? (
          <>
            <OiProfileBars bars={model.bars} />
            {model.pcr != null && (
              <Badge variant={pcrVariant(model.pcr)} className="font-mono text-xs">
                PCR {model.pcr.toFixed(2)}
                <span className="ml-1 font-sans font-normal opacity-70">
                  {pcrLean(model.pcr)}
                </span>
              </Badge>
            )}
          </>
        ) : model.kind === "loading" ? (
          <span className="text-xs text-text-muted">Loading OI…</span>
        ) : (
          <span className="text-xs text-text-muted">{model.emptyReason}</span>
        )}
      </div>
    </section>
  );
}

export default memo(OiPcrStrip);
