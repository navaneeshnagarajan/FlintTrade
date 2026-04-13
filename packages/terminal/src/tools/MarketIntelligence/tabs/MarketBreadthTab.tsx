import { Activity, TrendingDown, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { BREADTH_DATA } from "../data";
import { DataNotice, SectionLabel } from "../shared";

export function MarketBreadthTab() {
  const totalAdvances = BREADTH_DATA.reduce((a, b) => a + b.advances, 0);
  const totalDeclines = BREADTH_DATA.reduce((a, b) => a + b.declines, 0);
  const totalUnchanged = BREADTH_DATA.reduce((a, b) => a + b.unchanged, 0);
  const totalStocks = BREADTH_DATA.reduce((a, b) => a + b.total, 0);

  const adRatio = totalDeclines > 0 ? (totalAdvances / totalDeclines).toFixed(2) : "--";
  const breadthThrustRaw =
    totalAdvances + totalDeclines > 0
      ? (totalAdvances / (totalAdvances + totalDeclines)) * 100
      : 0;

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-5">
        <DataNotice />

        <div className="grid grid-cols-3 gap-2">
          {[
            { label: "Advances", value: totalAdvances, color: "text-profit", bg: "bg-bullish-bg border-bullish-border" },
            { label: "Declines", value: totalDeclines, color: "text-loss", bg: "bg-bearish-bg border-bearish-border" },
            { label: "Unchanged", value: totalUnchanged, color: "text-text-secondary", bg: "bg-surface-card border-border-default" },
          ].map((c) => (
            <Card key={c.label} className={`border ${c.bg}`}>
              <CardContent className="pt-3 pb-3 px-4">
                <div className={`text-xl font-mono font-bold tabular-nums ${c.color}`}>{c.value}</div>
                <div className="text-xs text-text-muted mt-0.5">{c.label} (of {totalStocks})</div>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Card className="bg-surface-card border-border-default">
            <CardContent className="pt-3 pb-3 px-4">
              <div className="text-xs text-text-muted mb-1">A/D Ratio</div>
              <div className={`text-xl font-mono font-bold tabular-nums ${parseFloat(adRatio) >= 1 ? "text-profit" : "text-loss"}`}>
                {adRatio}
              </div>
              <div className="text-xs text-text-muted mt-0.5">
                {parseFloat(adRatio) >= 1.5
                  ? "Strongly Bullish"
                  : parseFloat(adRatio) >= 1.0
                  ? "Mildly Bullish"
                  : parseFloat(adRatio) >= 0.67
                  ? "Mildly Bearish"
                  : "Strongly Bearish"}
              </div>
            </CardContent>
          </Card>
          <Card className="bg-surface-card border-border-default">
            <CardContent className="pt-3 pb-3 px-4">
              <div className="text-xs text-text-muted mb-1">Breadth Thrust</div>
              <div className={`text-xl font-mono font-bold tabular-nums ${breadthThrustRaw >= 61.5 ? "text-profit" : breadthThrustRaw >= 40 ? "text-text-secondary" : "text-loss"}`}>
                {breadthThrustRaw.toFixed(1)}%
              </div>
              <div className="text-xs text-text-muted mt-0.5">
                {breadthThrustRaw >= 61.5 ? "Bullish signal (>61.5%)" : breadthThrustRaw >= 40 ? "Neutral zone" : "Bearish zone (<40%)"}
              </div>
            </CardContent>
          </Card>
        </div>

        <div>
          <SectionLabel icon={Activity} label="Index-wise Breadth" />
          <div className="space-y-2">
            {BREADTH_DATA.map((bd) => {
              const advPct = ((bd.advances / bd.total) * 100).toFixed(0);
              const decPct = ((bd.declines / bd.total) * 100).toFixed(0);
              const unchPct = (100 - parseInt(advPct) - parseInt(decPct)).toFixed(0);
              return (
                <Card key={bd.label} className="bg-surface-card border-border-default">
                  <CardContent className="pt-3 pb-3 px-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs text-text-primary font-medium">{bd.label}</span>
                      <div className="flex items-center gap-3 text-xs">
                        <span className="text-profit">
                          <TrendingUp size={10} className="inline mr-0.5" />
                          {bd.advances} ({advPct}%)
                        </span>
                        <span className="text-loss">
                          <TrendingDown size={10} className="inline mr-0.5" />
                          {bd.declines} ({decPct}%)
                        </span>
                        <span className="text-text-muted">{bd.unchanged} Unch</span>
                      </div>
                    </div>
                    <div className="h-2 bg-surface-elevated rounded-full overflow-hidden flex gap-px">
                      <div className="h-full bg-profit transition-[width]" style={{ width: `${advPct}%` }} />
                      <div className="h-full bg-surface-active transition-[width]" style={{ width: `${unchPct}%` }} />
                      <div className="h-full bg-loss transition-[width]" style={{ width: `${decPct}%` }} />
                    </div>
                    <div className="flex items-center gap-4 mt-2 text-xs text-text-muted">
                      <span>52W High: <span className="text-profit">{bd.newHighs}</span></span>
                      <span>52W Low: <span className="text-loss">{bd.newLows}</span></span>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}
