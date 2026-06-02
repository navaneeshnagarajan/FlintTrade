import { ShieldAlert } from "lucide-react";
import { FlintLinearMeter } from "@flinttrade/design-system";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { DataNotice } from "../shared";

export function IndiaVixTab() {
  const vixValue = 14.28;
  const vixChange = -0.42;
  const vixChangePct = -2.86;

  function getVixZone(v: number): { label: string; description: string; color: string; bg: string } {
    if (v < 12) return { label: "Extreme Complacency", description: "Markets are extremely calm. Options are cheap. Consider buying protection.", color: "text-blue-400", bg: "bg-blue-500/10 border-blue-500/20" };
    if (v < 16) return { label: "Low Volatility", description: "Fear is low. Markets are trending. Options premiums are affordable.", color: "text-profit", bg: "bg-bullish-bg border-bullish-border" };
    if (v < 20) return { label: "Moderate Volatility", description: "Normal market conditions. Options are fairly priced.", color: "text-warning", bg: "bg-atm-bg border-atm-border" };
    if (v < 25) return { label: "Elevated Fear", description: "Increased uncertainty. Traders are hedging more aggressively.", color: "text-orange-400", bg: "bg-orange-500/10 border-orange-500/20" };
    if (v < 30) return { label: "High Fear", description: "Significant market stress. Strong sell-off likely in progress.", color: "text-loss", bg: "bg-bearish-bg border-bearish-border" };
    return { label: "Panic Zone", description: "Extreme fear and market stress. Historically a contrarian buy signal.", color: "text-loss", bg: "bg-bearish-bg border-bearish-border" };
  }

  const zone = getVixZone(vixValue);
  const vix52wLow = 10.84;
  const vix52wHigh = 28.42;

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <DataNotice text="India VIX is the NSE volatility index. Connect OpenAlgo quotes endpoint for live VIX data. Values shown are representative." />

        <Card className={`border ${zone.bg}`}>
          <CardContent className="pt-4 pb-4 px-5">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-xs text-text-muted mb-1 flex items-center gap-1">
                  <ShieldAlert size={11} />
                  India VIX — Volatility Index
                </div>
                <div className={`text-4xl font-mono font-bold tabular-nums leading-none ${zone.color}`}>
                  {vixValue.toFixed(2)}
                </div>
                <div className={`text-sm font-mono tabular-nums mt-1 ${vixChange >= 0 ? "text-profit" : "text-loss"}`}>
                  {vixChange >= 0 ? "+" : ""}{vixChange.toFixed(2)} ({vixChangePct.toFixed(2)}%)
                </div>
              </div>
              <Badge className={`text-xs px-2.5 py-1 border ${zone.bg} ${zone.color}`}>
                {zone.label}
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-surface-card border-border-default">
          <CardContent className="pt-4 pb-4 px-5">
            <div className="text-xs text-text-muted mb-3">52-Week Range</div>
            <FlintLinearMeter
              ariaLabel="India VIX 52-week range"
              value={vixValue}
              minValue={vix52wLow}
              maxValue={vix52wHigh}
              fillColor="linear-gradient(90deg, #10b981, #f59e0b, #ef4444)"
              marker
            />
            <div className="flex justify-between mt-2 text-xs font-mono">
              <span className="text-profit">{vix52wLow.toFixed(2)} (52W Low)</span>
              <span className="text-loss">{vix52wHigh.toFixed(2)} (52W High)</span>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-surface-card border-border-default">
          <CardContent className="pt-4 pb-4 px-5 space-y-3">
            <div className="text-xs font-semibold text-text-primary">What is India VIX?</div>
            <p className="text-xs text-text-secondary leading-relaxed">
              India VIX (Volatility Index) is computed by NSE based on the order book of Nifty options.
              It represents the market&apos;s expectation of volatility over the next 30 calendar days.
              A higher VIX means higher expected volatility and uncertainty — traders call it the
              &quot;fear gauge&quot;.
            </p>
            <div className="space-y-2">
              {[
                { range: "Below 12", meaning: "Extreme complacency — markets at peak confidence", color: "text-blue-400" },
                { range: "12 – 16", meaning: "Low volatility — trending bull market", color: "text-profit" },
                { range: "16 – 20", meaning: "Normal volatility — healthy market conditions", color: "text-warning" },
                { range: "20 – 25", meaning: "Elevated fear — watch for trend reversal", color: "text-orange-400" },
                { range: "25 – 30", meaning: "High fear — significant selling pressure", color: "text-loss" },
                { range: "Above 30", meaning: "Panic zone — historically extreme buy signal", color: "text-loss" },
              ].map((row) => (
                <div key={row.range} className="flex items-start gap-2 text-xs">
                  <span className={`font-mono font-medium w-20 shrink-0 ${row.color}`}>{row.range}</span>
                  <span className="text-text-secondary">{row.meaning}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className={`border ${zone.bg}`}>
          <CardContent className="pt-3 pb-3 px-5">
            <div className={`text-xs font-semibold mb-1 ${zone.color}`}>Current Interpretation</div>
            <p className="text-xs text-text-secondary">{zone.description}</p>
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  );
}
