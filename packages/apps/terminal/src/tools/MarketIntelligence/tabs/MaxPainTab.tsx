import { useEffect, useMemo } from "react";
import { Activity, Target } from "lucide-react";
import { FlintStackedBarChart, type FlintStackedBarSeries } from "@flinttrade/design-system";
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

interface MaxPainTabProps {
  onSampleDataChange?: (isSampleData: boolean | null) => void;
}

export function MaxPainTab({ onSampleDataChange }: MaxPainTabProps = {}) {
  const { state, setSymbol, setExchange, setExpiry } = useLiveSelector();
  const { data, isLoading, isError, error, refetch } = useMaxPain(
    state.symbol,
    state.exchange,
    state.expiry ?? undefined,
  );
  const maxPainStrike = typeof data?.max_pain_strike === "number"
    && Number.isFinite(data.max_pain_strike)
    && data.max_pain_strike > 0
    ? data.max_pain_strike
    : null;
  const hasUsableData = Boolean(data && data.strikes.length > 0 && maxPainStrike !== null);
  const sampleFlag = isError || !hasUsableData || !data
    ? null
    : data.is_sample_data !== false;

  useEffect(() => {
    onSampleDataChange?.(sampleFlag);
  }, [onSampleDataChange, sampleFlag]);

  useEffect(() => () => {
    onSampleDataChange?.(null);
  }, [onSampleDataChange]);

  const maxTotalPain = useMemo(() => {
    if (!data?.strikes?.length) return 1;
    return Math.max(...data.strikes.map((s) => s.total_pain), 1);
  }, [data]);
  const painLabels = useMemo(() => {
    if (!data?.strikes?.length) return [];
    return data.strikes.map((row) => {
      const strike = row.strike.toLocaleString("en-IN");
      return row.strike === maxPainStrike ? `${strike} MAX` : strike;
    });
  }, [data, maxPainStrike]);
  const painSeries = useMemo<FlintStackedBarSeries[]>(() => {
    if (!data?.strikes?.length) return [];
    const hasPainComponents = data.strikes.every(
      (row) => row.call_pain !== undefined && row.put_pain !== undefined,
    );
    if (!hasPainComponents) {
      return [{
        label: "Total Pain",
        color: "rgba(14, 165, 233, 0.72)",
        values: data.strikes.map((row) => row.total_pain),
      }];
    }
    return [
      {
        label: "Call Pain",
        color: "rgba(16, 185, 129, 0.72)",
        values: data.strikes.map((row) => row.call_pain!),
      },
      {
        label: "Put Pain",
        color: "rgba(239, 68, 68, 0.72)",
        values: data.strikes.map((row) => row.put_pain!),
      },
    ];
  }, [data]);

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <DataNotice text="Max Pain is the strike price where option buyers would collectively lose the most at expiry. Historically, price tends to gravitate toward max pain as expiry approaches. Refreshes every 60s during market hours." />

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
        ) : data && data.strikes.length > 0 && maxPainStrike !== null ? (
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
                      {maxPainStrike.toLocaleString("en-IN")}
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
                <FlintStackedBarChart
                  ariaLabel="Max pain distribution across strikes"
                  labels={painLabels}
                  series={painSeries}
                  maxValue={maxTotalPain}
                  valueFormatter={formatOINum}
                  className="mt-2"
                />
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
                        const isMaxPain = row.strike === maxPainStrike;
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
                            <TableCell className="px-2 py-1.5 font-mono text-xs text-profit">
                              {row.call_oi === undefined ? "--" : formatOINum(row.call_oi)}
                            </TableCell>
                            <TableCell className="px-2 py-1.5 font-mono text-xs text-loss">
                              {row.put_oi === undefined ? "--" : formatOINum(row.put_oi)}
                            </TableCell>
                            <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">
                              {row.call_pain === undefined ? "--" : formatOINum(row.call_pain)}
                            </TableCell>
                            <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">
                              {row.put_pain === undefined ? "--" : formatOINum(row.put_pain)}
                            </TableCell>
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
