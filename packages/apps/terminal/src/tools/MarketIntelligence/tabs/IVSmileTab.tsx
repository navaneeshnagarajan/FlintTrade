import { useMemo } from "react";
import { Activity, LineChart } from "lucide-react";
import { FlintMultiLineChart } from "@flinttrade/design-system";
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

  const chartState = useMemo(() => {
    if (!data?.length) return null;

    const strikes = data.map((row) => row.strike);
    const strikeMin = Math.min(...strikes);
    const strikeMax = Math.max(...strikes);
    const yMax = Math.max(maxIV * 1.12, 1);
    const tickEvery = Math.max(1, Math.ceil(data.length / 5));
    const xTicks = data
      .filter((_, index) => index % tickEvery === 0)
      .map((row) => row.strike);

    return {
      xDomain: [strikeMin, strikeMax] as const,
      yDomain: [0, yMax] as const,
      xTicks,
      yTicks: [0, Math.round(yMax / 2), Math.round(yMax)],
      series: [
        {
          id: "call-iv",
          label: "Call IV",
          color: "#0ea5e9",
          points: data.map((row) => ({
            x: row.strike,
            y: row.call_iv,
            label: `${row.strike.toLocaleString("en-IN")} call IV ${row.call_iv.toFixed(2)}%`,
          })),
        },
        {
          id: "put-iv",
          label: "Put IV",
          color: "#f59e0b",
          points: data.map((row) => ({
            x: row.strike,
            y: row.put_iv,
            label: `${row.strike.toLocaleString("en-IN")} put IV ${row.put_iv.toFixed(2)}%`,
          })),
        },
      ],
    };
  }, [data, maxIV]);

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
              {chartState && (
                <div className="rounded-md border border-border-default bg-surface-card/40 p-2">
                  <FlintMultiLineChart
                    ariaLabel="IV Smile call and put volatility by strike"
                    series={chartState.series}
                    xDomain={chartState.xDomain}
                    yDomain={chartState.yDomain}
                    xTicks={chartState.xTicks}
                    yTicks={chartState.yTicks}
                    xFormatter={(value) => value.toLocaleString("en-IN")}
                    yFormatter={(value) => `${value.toFixed(0)}%`}
                    xAxisLabel="Strike"
                    yAxisLabel="IV"
                    referenceLines={atmStrike !== null
                      ? [{ axis: "x", value: atmStrike, color: "var(--color-primary, #818cf8)", dash: "4,3" }]
                      : []}
                    width={560}
                    height={220}
                  />
                </div>
              )}
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
