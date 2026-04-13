import { ChevronRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { CORR_ASSETS, CORR_MATRIX } from "../data";
import { DataNotice } from "../shared";
import { getThemeColor } from "../utils";

export function CorrelationMatrixTab() {
  function getCorrColor(v: number): { bg: string; text: string } {
    if (v >= 0.7) return { bg: "#064e3b", text: "#a7f3d0" };
    if (v >= 0.4) return { bg: "#065f46", text: "#6ee7b7" };
    if (v >= 0.1) return { bg: "#047857", text: "#d1fae5" };
    if (v >= -0.1) return { bg: getThemeColor("--color-card", "#16161f"), text: getThemeColor("--color-text-muted", "#9090b0") };
    if (v >= -0.4) return { bg: "#7f1d1d", text: "#fca5a5" };
    if (v >= -0.7) return { bg: "#991b1b", text: "#f87171" };
    return { bg: "#450a0a", text: "#fca5a5" };
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <DataNotice text="Correlation computed from approximate 1-year rolling daily returns. Illustrative values — connect data source for live correlations." />

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="text-xs text-text-muted font-normal px-2 py-1.5 text-left w-20" />
                {CORR_ASSETS.map((asset) => (
                  <th key={asset} className="text-xs text-text-secondary font-medium px-2 py-1.5 text-center">
                    {asset}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CORR_MATRIX.map((row, ri) => (
                <tr key={CORR_ASSETS[ri]}>
                  <td className="text-xs text-text-secondary font-medium px-2 py-1 text-right pr-3">
                    {CORR_ASSETS[ri]}
                  </td>
                  {row.map((val, ci) => {
                    const colors = getCorrColor(val);
                    return (
                      <td key={ci} className="px-1 py-1">
                        <div
                          className="w-16 h-10 rounded flex items-center justify-center font-mono text-xs font-semibold transition-opacity hover:opacity-90 cursor-default"
                          style={{ backgroundColor: colors.bg, color: colors.text }}
                          title={`${CORR_ASSETS[ri]} vs ${CORR_ASSETS[ci]}: ${val.toFixed(2)}`}
                        >
                          {val === 1.0 ? "1.00" : val.toFixed(2)}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="space-y-2">
          <div className="text-xs text-text-muted font-medium">How to read:</div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            {[
              { range: "0.7 to 1.0", desc: "Strong positive — move together", bg: "#064e3b", text: "#a7f3d0" },
              { range: "0.4 to 0.7", desc: "Moderate positive correlation", bg: "#065f46", text: "#6ee7b7" },
              { range: "0.1 to 0.4", desc: "Weak positive correlation", bg: "#047857", text: "#d1fae5" },
              { range: "-0.1 to 0.1", desc: "Uncorrelated / neutral", bg: getThemeColor("--color-card", "#16161f"), text: getThemeColor("--color-text-muted", "#9090b0") },
              { range: "-0.4 to -0.1", desc: "Weak negative correlation", bg: "#7f1d1d", text: "#fca5a5" },
              { range: "-1.0 to -0.4", desc: "Strong negative — move oppositely", bg: "#450a0a", text: "#fca5a5" },
            ].map((l) => (
              <div key={l.range} className="flex items-center gap-2">
                <span
                  className="w-8 h-5 rounded text-center font-mono text-xxs flex items-center justify-center shrink-0"
                  style={{ backgroundColor: l.bg, color: l.text }}
                >
                  {l.range.split(" ")[0]}
                </span>
                <span className="text-xs text-text-muted">{l.desc}</span>
              </div>
            ))}
          </div>
        </div>

        <Card className="bg-surface-card border-border-default">
          <CardContent className="pt-3 pb-3 px-4 space-y-2">
            <div className="text-xs font-semibold text-text-primary">Key Observations</div>
            <ul className="space-y-1.5 text-xs text-text-secondary">
              <li className="flex items-start gap-2"><ChevronRight size={11} className="text-primary mt-0.5 shrink-0" />VIX and Nifty have a strong negative correlation (-0.72). Rising VIX typically signals falling markets.</li>
              <li className="flex items-start gap-2"><ChevronRight size={11} className="text-primary mt-0.5 shrink-0" />Gold and USD-INR are positively correlated (0.48). Rupee depreciation often drives gold prices higher in INR terms.</li>
              <li className="flex items-start gap-2"><ChevronRight size={11} className="text-primary mt-0.5 shrink-0" />Nifty and USD-INR are negatively correlated (-0.62). FII outflows weaken the rupee and pressure equities simultaneously.</li>
              <li className="flex items-start gap-2"><ChevronRight size={11} className="text-primary mt-0.5 shrink-0" />Gold and Crude have a weak positive correlation (0.28), driven by common USD and geopolitical factors.</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  );
}
