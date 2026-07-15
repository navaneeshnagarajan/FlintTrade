import { useEffect, useMemo } from "react";
import { Activity, Layers } from "lucide-react";
import { FlintDivergingBarList } from "@flinttrade/design-system";
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
import { useOIProfile } from "@/hooks/useMarketIntel";
import { DataNotice, ErrorRetry, LiveSelector, SectionLabel, useLiveSelector } from "../shared";
import { OI_BUILDUP_COLORS } from "../data";
import { formatOINum, netColor } from "../utils";
import type { OIBuildUp, StrikeEntry } from "../types";

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function getOIBuildUp(oi: number, oiDelta: number, priceChange: number): OIBuildUp | null {
  if (![oi, oiDelta, priceChange].every(Number.isFinite)) return null;
  const oiUp = oiDelta > 0;
  const priceUp = priceChange > 0;
  if (oiDelta === 0 || priceChange === 0 || Math.abs(oiDelta) < oi * 0.005) return "Neutral";
  if (oiUp && priceUp) return "Long Build Up";
  if (oiUp && !priceUp) return "Short Build Up";
  if (!oiUp && priceUp) return "Short Covering";
  return "Long Unwinding";
}

interface OIProfileTabProps {
  onSampleDataChange?: (isSampleData: boolean | null) => void;
}

export function OIProfileTab({ onSampleDataChange }: OIProfileTabProps = {}) {
  const { state, setSymbol, setExchange, setExpiry } = useLiveSelector();
  const { data, isLoading, isError, error, refetch } = useOIProfile(
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

  const strikeMap = useMemo(() => {
    const m: Map<number, StrikeEntry> = new Map<number, StrikeEntry>();
    if (!rows?.length) return m;
    for (const entry of rows) {
      const existing: StrikeEntry = m.get(entry.strike) ?? { ce: null, pe: null };
      if (entry.type === "CE") existing.ce = entry;
      else existing.pe = entry;
      m.set(entry.strike, existing);
    }
    return m;
  }, [rows]);

  const strikes = useMemo(() => Array.from(strikeMap.keys()).sort((a, b) => a - b), [strikeMap]);

  const maxOI = useMemo(() => {
    if (!rows?.length) return 1;
    return Math.max(...rows.map((d) => d.oi), 1);
  }, [rows]);
  const oiProfileEntries = useMemo(() => {
    return strikes.map((strike) => {
      const entry = strikeMap.get(strike)!;
      const ceOI = entry.ce?.oi ?? null;
      const peOI = entry.pe?.oi ?? null;
      return {
        label: strike.toLocaleString("en-IN"),
        leftValue: peOI ?? 0,
        rightValue: ceOI ?? 0,
        leftLabel: peOI === null ? "--" : formatOINum(peOI),
        rightLabel: ceOI === null ? "--" : formatOINum(ceOI),
      };
    });
  }, [strikeMap, strikes]);

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <DataNotice text="OI Profile displays open interest distribution across strikes. CE bars go right (green), PE bars go left (red). OI changes help identify build-up or unwinding. Refreshes every 30s during market hours." />

        <LiveSelector state={state} setSymbol={setSymbol} setExchange={setExchange} setExpiry={setExpiry} />

        {isLoading ? (
          <div className="space-y-1.5">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-7 bg-surface-elevated rounded animate-pulse" />
            ))}
          </div>
        ) : isError ? (
          <ErrorRetry message={(error as Error)?.message ?? "Failed to load OI Profile data"} onRetry={() => void refetch()} />
        ) : strikes.length > 0 ? (
          <>
            <div>
              <SectionLabel icon={Layers} label="OI Profile — CE (right) vs PE (left)" />
              <FlintDivergingBarList
                ariaLabel="OI profile by strike"
                entries={oiProfileEntries}
                maxValue={maxOI}
                leftHeading="PE OI"
                rightHeading="CE OI"
              />
            </div>

            <div>
              <SectionLabel icon={Activity} label="OI Profile Data Table" />
              <div className="rounded-md border border-border-default overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow className="border-border-default hover:bg-transparent">
                      {["Strike", "CE OI", "PE OI", "CE OI Chg", "PE OI Chg", "CE LTP", "PE LTP", "Signal"].map((h) => (
                        <TableHead key={h} className="text-xs text-text-muted h-8 px-2">{h}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {strikes.map((strike) => {
                      const entry = strikeMap.get(strike)!;
                      const ceOI = finiteNumber(entry.ce?.oi);
                      const peOI = finiteNumber(entry.pe?.oi);
                      const ceDelta = finiteNumber(entry.ce?.oi_delta_d);
                      const peDelta = finiteNumber(entry.pe?.oi_delta_d);
                      const ceLtp = finiteNumber(entry.ce?.ltp);
                      const peLtp = finiteNumber(entry.pe?.ltp);
                      const cePriceChange = finiteNumber(entry.ce?.price_change);
                      const ceSignal = ceOI === null || ceDelta === null || cePriceChange === null
                        ? null
                        : getOIBuildUp(ceOI, ceDelta, cePriceChange);
                      return (
                        <TableRow key={strike} className="border-border-default hover:bg-surface-card">
                          <TableCell className="px-2 py-1.5 font-mono text-xs font-semibold text-text-primary">
                            {strike.toLocaleString("en-IN")}
                          </TableCell>
                          <TableCell className="px-2 py-1.5 font-mono text-xs text-profit">
                            {ceOI === null ? "--" : formatOINum(ceOI)}
                          </TableCell>
                          <TableCell className="px-2 py-1.5 font-mono text-xs text-loss">
                            {peOI === null ? "--" : formatOINum(peOI)}
                          </TableCell>
                          <TableCell className={`px-2 py-1.5 font-mono text-xs ${ceDelta === null ? "text-text-muted" : netColor(ceDelta)}`}>
                            {ceDelta === null ? "--" : `${ceDelta > 0 ? "+" : ""}${formatOINum(ceDelta)}`}
                          </TableCell>
                          <TableCell className={`px-2 py-1.5 font-mono text-xs ${peDelta === null ? "text-text-muted" : netColor(peDelta)}`}>
                            {peDelta === null ? "--" : `${peDelta > 0 ? "+" : ""}${formatOINum(peDelta)}`}
                          </TableCell>
                          <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">
                            {ceLtp === null ? "--" : ceLtp.toFixed(2)}
                          </TableCell>
                          <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">
                            {peLtp === null ? "--" : peLtp.toFixed(2)}
                          </TableCell>
                          <TableCell className="px-2 py-1.5">
                            {ceSignal === null ? (
                              <span className="font-mono text-xs text-text-muted">--</span>
                            ) : (
                              <Badge className={`text-xxs h-5 px-1.5 bg-transparent border ${OI_BUILDUP_COLORS[ceSignal]}`}>
                                {ceSignal}
                              </Badge>
                            )}
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
            No OI Profile data available. Select a symbol and expiry above.
          </div>
        )}
      </div>
    </ScrollArea>
  );
}
