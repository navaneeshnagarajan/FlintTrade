import { useMemo } from "react";
import { Activity, Target } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useMaxPain } from "@/hooks/useMarketIntel";
import { DataNotice, ErrorRetry, LiveSelector, LoadingRows, SectionLabel, useLiveSelector } from "../shared";
import { formatOINum } from "../utils";

export function MaxPainTab() {
  const { state, setSymbol, setExchange, setExpiry } = useLiveSelector();
  const { data, isLoading, isError, error, refetch } = useMaxPain(
    state.symbol,
    state.exchange,
    state.expiry ?? undefined,
  );

  const maxTotalPain = useMemo(() => {
    if (!data?.strikes?.length) return 1;
    return Math.max(...data.strikes.map((s) => s.total_pain), 1);
  }, [data]);

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <DataNotice text="Max Pain is the strike price where option buyers would collectively lose the most at expiry. Historically, price tends to gravitate toward max pain as expiry approaches. Refreshes every 30s during market hours." />

        <LiveSelector state={state} setSymbol={setSymbol} setExchange={setExchange} setExpiry={setExpiry} />

        {isLoading ? (
          <div className="space-y-3">
            <div className="h-20 bg-surface-elevated rounded animate-pulse" />
            <div className="space-y-1.5">
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="h-7 bg-surface-elevated rounded animate-pulse" />
              ))}
            </div>
          </div>
        ) : isError ? (
          <ErrorRetry message={(error as Error)?.message ?? "Failed to load Max Pain data"} onRetry={() => void refetch()} />
        ) : data ? (
          <>
            <Card className="bg-surface-card border-primary/30">
              <CardContent className="pt-4 pb-4 px-5">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs text-text-muted mb-1 flex items-center gap-1">
                      <Target size={11} />
                      Max Pain Strike
                    </div>
                    <div className="text-4xl font-mono font-bold tabular-nums text-primary">
                      {data.max_pain_strike.toLocaleString("en-IN")}
                    </div>
                    <div className="text-xs text-text-secondary mt-1">
                      {state.symbol} · {state.exchange} · {state.expiry ?? "—"}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-text-muted">Option writers profit</div>
                    <div className="text-xs text-text-muted mt-0.5">maximally at this strike</div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {data.strikes.length > 0 && (
              <div>
                <SectionLabel icon={Target} label="Pain Distribution Across Strikes" />
                <div className="flex items-center gap-4 mb-2 text-xs">
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-2 rounded bg-emerald-600 inline-block" />
                    <span className="text-text-muted">Call Pain</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-2 rounded bg-red-600 inline-block" />
                    <span className="text-text-muted">Put Pain</span>
                  </div>
                </div>
                <div className="space-y-px">
                  {data.strikes.map((row) => {
                    const isMaxPain = row.strike === data.max_pain_strike;
                    const totalPct = (row.total_pain / maxTotalPain) * 100;
                    const callPct = row.total_pain > 0 ? (row.call_pain / row.total_pain) * totalPct : 0;
                    const putPct = totalPct - callPct;
                    return (
                      <div
                        key={row.strike}
                        className={[
                          "flex items-center gap-2 px-1 py-0.5 rounded",
                          isMaxPain ? "bg-primary/10 border border-primary/30" : "",
                        ].join(" ")}
                      >
                        <span className="font-mono text-xs w-16 text-right shrink-0 text-text-muted">
                          {row.strike.toLocaleString("en-IN")}
                          {isMaxPain && <span className="ml-1 text-primary text-xxs">MAX</span>}
                        </span>
                        <div className="flex-1 flex h-4 rounded overflow-hidden bg-surface-elevated">
                          <div
                            className="h-full bg-emerald-600/70"
                            style={{ width: `${callPct}%` }}
                            title={`Call Pain: ${row.call_pain.toFixed(0)}`}
                          />
                          <div
                            className="h-full bg-red-600/70"
                            style={{ width: `${putPct}%` }}
                            title={`Put Pain: ${row.put_pain.toFixed(0)}`}
                          />
                        </div>
                        <span className="font-mono text-xs w-20 text-right shrink-0 text-text-secondary">
                          {formatOINum(row.total_pain)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div>
              <SectionLabel icon={Activity} label="Max Pain Data Table" />
              <div className="rounded-md border border-border-default overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border-default hover:bg-transparent">
                      {["Strike", "Call OI", "Put OI", "Call Pain", "Put Pain", "Total Pain"].map((h) => (
                        <TableHead key={h} className="text-xs text-text-muted h-8 px-2">{h}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {isLoading ? (
                      <LoadingRows cols={6} />
                    ) : (
                      data.strikes.map((row) => {
                        const isMaxPain = row.strike === data.max_pain_strike;
                        return (
                          <TableRow
                            key={row.strike}
                            className={["border-border-default hover:bg-surface-card", isMaxPain ? "bg-primary/5" : ""].join(" ")}
                          >
                            <TableCell className="px-2 py-1.5 font-mono text-xs font-semibold text-text-primary">
                              {row.strike.toLocaleString("en-IN")}
                              {isMaxPain && (
                                <Badge className="ml-2 text-xxs h-4 px-1.5 bg-transparent border border-primary text-primary">
                                  MAX
                                </Badge>
                              )}
                            </TableCell>
                            <TableCell className="px-2 py-1.5 font-mono text-xs text-profit">{formatOINum(row.call_oi)}</TableCell>
                            <TableCell className="px-2 py-1.5 font-mono text-xs text-loss">{formatOINum(row.put_oi)}</TableCell>
                            <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">{formatOINum(row.call_pain)}</TableCell>
                            <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">{formatOINum(row.put_pain)}</TableCell>
                            <TableCell className="px-2 py-1.5 font-mono text-xs font-semibold text-text-primary">{formatOINum(row.total_pain)}</TableCell>
                          </TableRow>
                        );
                      })
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>
          </>
        ) : (
          <div className="text-center py-8 text-xs text-text-muted">
            No Max Pain data available. Select a symbol and expiry above.
          </div>
        )}
      </div>
    </ScrollArea>
  );
}
