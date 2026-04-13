import { useMemo } from "react";
import { Activity, Flame } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useGex } from "@/hooks/useMarketIntel";
import { DataNotice, ErrorRetry, LiveSelector, SectionLabel, useLiveSelector } from "../shared";
import { formatOINum } from "../utils";

export function GexTab() {
  const { state, setSymbol, setExchange, setExpiry } = useLiveSelector();
  const { data, isLoading, isError, error, refetch } = useGex(
    state.symbol,
    state.exchange,
    state.expiry ?? undefined,
  );

  const maxAbsGamma = useMemo(() => {
    if (!data?.length) return 1;
    return Math.max(...data.map((d) => Math.abs(d.net_gamma)), 1);
  }, [data]);

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <DataNotice text="Gamma Exposure (GEX) shows where market-makers are hedging. Positive net gamma = dealers are long gamma (stabilising). Negative = short gamma (amplifying moves). Refreshes every 30s during market hours." />

        <LiveSelector state={state} setSymbol={setSymbol} setExchange={setExchange} setExpiry={setExpiry} />

        {isLoading ? (
          <div className="space-y-1.5">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-7 bg-surface-elevated rounded animate-pulse" />
            ))}
          </div>
        ) : isError ? (
          <ErrorRetry message={(error as Error)?.message ?? "Failed to load GEX data"} onRetry={() => void refetch()} />
        ) : data && data.length > 0 ? (
          <>
            <div>
              <SectionLabel icon={Flame} label="Net Gamma Exposure by Strike" />
              <div className="space-y-px">
                {data.map((row) => {
                  const barPct = (Math.abs(row.net_gamma) / maxAbsGamma) * 100;
                  const isPos = row.net_gamma >= 0;
                  return (
                    <div key={row.strike} className="flex items-center gap-2 group">
                      <span className="font-mono text-xs text-text-muted w-16 text-right shrink-0">
                        {row.strike.toLocaleString("en-IN")}
                      </span>
                      <div className="flex-1 relative h-5 flex items-center">
                        <div className="absolute inset-0 flex items-center">
                          <div className="w-full h-px bg-border-default" />
                        </div>
                        {isPos ? (
                          <div
                            className="absolute left-1/2 h-4 rounded-r"
                            style={{ width: `${barPct / 2}%`, backgroundColor: "#10b981", opacity: 0.75 }}
                          />
                        ) : (
                          <div
                            className="absolute right-1/2 h-4 rounded-l"
                            style={{ width: `${barPct / 2}%`, backgroundColor: "#ef4444", opacity: 0.75 }}
                          />
                        )}
                      </div>
                      <span className={`font-mono text-xs w-20 shrink-0 ${isPos ? "text-profit" : "text-loss"}`}>
                        {isPos ? "+" : ""}{row.net_gamma.toFixed(2)}
                      </span>
                    </div>
                  );
                })}
              </div>
              <div className="flex justify-between text-xs text-text-muted mt-1 px-2">
                <span className="text-loss">Short Gamma (bearish amplifier)</span>
                <span className="text-profit">Long Gamma (market stabiliser)</span>
              </div>
            </div>

            <div>
              <SectionLabel icon={Activity} label="GEX Data Table" />
              <div className="rounded-md border border-border-default overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border-default hover:bg-transparent">
                      {["Strike", "Call Gamma", "Put Gamma", "Net Gamma", "Call OI", "Put OI"].map((h) => (
                        <TableHead key={h} className="text-xs text-text-muted h-8 px-2">{h}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.map((row) => (
                      <TableRow key={row.strike} className="border-border-default hover:bg-surface-card">
                        <TableCell className="px-2 py-1.5 font-mono text-xs font-semibold text-text-primary">
                          {row.strike.toLocaleString("en-IN")}
                        </TableCell>
                        <TableCell className="px-2 py-1.5 font-mono text-xs text-profit">{row.call_gamma.toFixed(4)}</TableCell>
                        <TableCell className="px-2 py-1.5 font-mono text-xs text-loss">{row.put_gamma.toFixed(4)}</TableCell>
                        <TableCell className={`px-2 py-1.5 font-mono text-xs font-semibold ${row.net_gamma >= 0 ? "text-profit" : "text-loss"}`}>
                          {row.net_gamma >= 0 ? "+" : ""}{row.net_gamma.toFixed(4)}
                        </TableCell>
                        <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">{formatOINum(row.call_oi)}</TableCell>
                        <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">{formatOINum(row.put_oi)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          </>
        ) : (
          <div className="text-center py-8 text-xs text-text-muted">
            No GEX data available. Select a symbol and expiry above.
          </div>
        )}
      </div>
    </ScrollArea>
  );
}
