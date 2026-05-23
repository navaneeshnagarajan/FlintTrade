import { useMemo } from "react";
import { Activity, LineChart } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useIVSmile } from "@/hooks/useMarketIntel";
import { DataNotice, ErrorRetry, LiveSelector, SectionLabel, useLiveSelector } from "../shared";

export function IVSmileTab() {
  const { state, setSymbol, setExchange, setExpiry } = useLiveSelector();
  const { data, isLoading, isError, error, refetch } = useIVSmile(
    state.symbol,
    state.exchange,
    state.expiry ?? undefined,
  );

  const atmStrike = useMemo(() => {
    if (!data?.length) return null;
    const atm = data.reduce((prev, cur) =>
      Math.abs(cur.moneyness) < Math.abs(prev.moneyness) ? cur : prev,
    );
    return atm.strike;
  }, [data]);

  const maxIV = useMemo(() => {
    if (!data?.length) return 1;
    return Math.max(...data.map((d) => Math.max(d.call_iv, d.put_iv)), 1);
  }, [data]);

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <DataNotice text="IV Smile shows implied volatility across strikes. A skewed smile indicates directional bias — higher put IV means market paying more for downside protection. Refreshes every 30s during market hours." />

        <LiveSelector state={state} setSymbol={setSymbol} setExchange={setExchange} setExpiry={setExpiry} />

        {isLoading ? (
          <div className="space-y-1.5">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-7 bg-surface-elevated rounded animate-pulse" />
            ))}
          </div>
        ) : isError ? (
          <ErrorRetry message={(error as Error)?.message ?? "Failed to load IV Smile data"} onRetry={() => void refetch()} />
        ) : data && data.length > 0 ? (
          <>
            <div>
              <SectionLabel icon={LineChart} label="IV Smile Chart" />
              <div className="flex items-center gap-4 mb-2 text-xs">
                <div className="flex items-center gap-1.5">
                  <span className="w-3 h-2 rounded bg-sky-500 inline-block" />
                  <span className="text-text-muted">Call IV</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-3 h-2 rounded bg-amber-500 inline-block" />
                  <span className="text-text-muted">Put IV</span>
                </div>
                {atmStrike !== null && (
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-2 rounded border border-primary inline-block" />
                    <span className="text-text-muted">ATM Strike</span>
                  </div>
                )}
              </div>
              <div className="space-y-1">
                {data.map((row) => {
                  const isAtm = row.strike === atmStrike;
                  const callPct = (row.call_iv / maxIV) * 100;
                  const putPct = (row.put_iv / maxIV) * 100;
                  return (
                    <div
                      key={row.strike}
                      className={[
                        "flex items-center gap-2 px-1 rounded",
                        isAtm ? "bg-primary/5 border border-primary/20" : "",
                      ].join(" ")}
                    >
                      <span className="font-mono text-xs w-16 text-right text-text-muted shrink-0">
                        {row.strike.toLocaleString("en-IN")}
                        {isAtm && <span className="ml-1 text-primary text-xxs">ATM</span>}
                      </span>
                      <div className="flex-1 flex flex-col gap-0.5 py-1">
                        <div
                          className="h-2 rounded"
                          style={{ width: `${callPct}%`, backgroundColor: "#0ea5e9", opacity: 0.8 }}
                          title={`Call IV: ${row.call_iv.toFixed(2)}%`}
                        />
                        <div
                          className="h-2 rounded"
                          style={{ width: `${putPct}%`, backgroundColor: "#f59e0b", opacity: 0.8 }}
                          title={`Put IV: ${row.put_iv.toFixed(2)}%`}
                        />
                      </div>
                      <span className="font-mono text-xs w-12 text-right text-sky-400 shrink-0">
                        {row.call_iv.toFixed(1)}%
                      </span>
                      <span className="font-mono text-xs w-12 text-right text-amber-400 shrink-0">
                        {row.put_iv.toFixed(1)}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div>
              <SectionLabel icon={Activity} label="IV Smile Data Table" />
              <div className="rounded-md border border-border-default overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border-default hover:bg-transparent">
                      {["Strike", "Call IV", "Put IV", "Moneyness"].map((h) => (
                        <TableHead key={h} className="text-xs text-text-muted h-8 px-3">{h}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.map((row) => {
                      const isAtm = row.strike === atmStrike;
                      return (
                        <TableRow
                          key={row.strike}
                          className={["border-border-default hover:bg-surface-card", isAtm ? "bg-primary/5" : ""].join(" ")}
                        >
                          <TableCell className="px-3 py-1.5 font-mono text-xs font-semibold text-text-primary">
                            {row.strike.toLocaleString("en-IN")}
                            {isAtm && (
                              <Badge className="ml-2 text-xxs h-4 px-1.5 bg-transparent border border-primary text-primary">
                                ATM
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell className="px-3 py-1.5 font-mono text-xs text-sky-400">{row.call_iv.toFixed(2)}%</TableCell>
                          <TableCell className="px-3 py-1.5 font-mono text-xs text-amber-400">{row.put_iv.toFixed(2)}%</TableCell>
                          <TableCell className={`px-3 py-1.5 font-mono text-xs ${row.moneyness > 0 ? "text-profit" : row.moneyness < 0 ? "text-loss" : "text-text-muted"}`}>
                            {row.moneyness > 0 ? "+" : ""}{row.moneyness.toFixed(2)}%
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            </div>
          </>
        ) : (
          <div className="text-center py-8 text-xs text-text-muted">
            No IV Smile data available. Select a symbol and expiry above.
          </div>
        )}
      </div>
    </ScrollArea>
  );
}
