import { useEffect, useMemo } from "react";
import { Activity, Flame } from "lucide-react";
import { FlintDivergingBarList } from "@flinttrade/design-system";
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

interface GexTabProps {
  onSampleDataChange?: (isSampleData: boolean | null) => void;
}

export function GexTab({ onSampleDataChange }: GexTabProps = {}) {
  const { state, setSymbol, setExchange, setExpiry } = useLiveSelector();
  const { data, isLoading, isError, error, refetch } = useGex(
    state.symbol,
    state.exchange,
    state.expiry ?? undefined,
  );
  const rows = data?.rows;
  const sampleFlag = isError || !data || !rows?.length
    ? null
    : data.is_sample_data !== false;

  useEffect(() => {
    onSampleDataChange?.(sampleFlag);
  }, [onSampleDataChange, sampleFlag]);

  useEffect(() => () => {
    onSampleDataChange?.(null);
  }, [onSampleDataChange]);

  const maxAbsExposure = useMemo(() => {
    if (!rows?.length) return 1;
    return Math.max(...rows.map((d) => Math.abs(d.net_gex)), 1);
  }, [rows]);
  const gexEntries = useMemo(() => {
    if (!rows?.length) return [];
    return rows.map((row) => {
      const isLong = row.net_gex > 0;
      const isShort = row.net_gex < 0;
      const formatted = `${isLong ? "+" : ""}${row.net_gex.toFixed(2)}`;
      return {
        label: row.strike.toLocaleString("en-IN"),
        leftValue: isShort ? Math.abs(row.net_gex) : 0,
        rightValue: isLong ? row.net_gex : 0,
        leftLabel: isShort ? formatted : "",
        rightLabel: isLong ? formatted : row.net_gex === 0 ? "Neutral" : "",
      };
    });
  }, [rows]);

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
        ) : rows && rows.length > 0 ? (
          <>
            <div>
              <SectionLabel icon={Flame} label="Net Gamma Exposure by Strike" />
              <FlintDivergingBarList
                ariaLabel="Net gamma exposure by strike"
                entries={gexEntries}
                maxValue={maxAbsExposure}
                leftHeading="Short gamma"
                rightHeading="Long gamma"
              />
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
                      {["Strike", "Call Exposure", "Put Exposure", "Net Exposure", "Call OI", "Put OI"].map((h) => (
                        <TableHead key={h} className="text-xs text-text-muted h-8 px-2">{h}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((row) => (
                      <TableRow key={row.strike} className="border-border-default hover:bg-surface-card">
                        <TableCell className="px-2 py-1.5 font-mono text-xs font-semibold text-text-primary">
                          {row.strike.toLocaleString("en-IN")}
                        </TableCell>
                        <TableCell className="px-2 py-1.5 font-mono text-xs text-profit">{row.call_gex.toFixed(4)}</TableCell>
                        <TableCell className="px-2 py-1.5 font-mono text-xs text-loss">{row.put_gex.toFixed(4)}</TableCell>
                        <TableCell className={`px-2 py-1.5 font-mono text-xs font-semibold ${
                          row.net_gex > 0
                            ? "text-profit"
                            : row.net_gex < 0 ? "text-loss" : "text-text-secondary"
                        }`}>
                          {row.net_gex > 0 ? "+" : ""}{row.net_gex.toFixed(4)}
                          {row.net_gex === 0 ? " Neutral" : ""}
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
