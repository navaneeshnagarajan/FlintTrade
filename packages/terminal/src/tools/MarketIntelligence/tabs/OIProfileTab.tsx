import { useMemo } from "react";
import { Activity, Layers } from "lucide-react";
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

function getOIBuildUp(oi: number, oiDelta: number, ltp: number): OIBuildUp {
  const oiUp = oiDelta > 0;
  const priceUp = ltp > 0;
  if (Math.abs(oiDelta) < oi * 0.005) return "Neutral";
  if (oiUp && priceUp) return "Long Build Up";
  if (oiUp && !priceUp) return "Short Build Up";
  if (!oiUp && priceUp) return "Short Covering";
  return "Long Unwinding";
}

export function OIProfileTab() {
  const { state, setSymbol, setExchange, setExpiry } = useLiveSelector();
  const { data, isLoading, isError, error, refetch } = useOIProfile(
    state.symbol,
    state.exchange,
    state.expiry ?? undefined,
  );

  const strikeMap = useMemo(() => {
    const m: Map<number, StrikeEntry> = new Map<number, StrikeEntry>();
    if (!data?.length) return m;
    for (const entry of data) {
      const existing: StrikeEntry = m.get(entry.strike) ?? { ce: null, pe: null };
      if (entry.type === "CE") existing.ce = entry;
      else existing.pe = entry;
      m.set(entry.strike, existing);
    }
    return m;
  }, [data]);

  const strikes = useMemo(() => Array.from(strikeMap.keys()).sort((a, b) => a - b), [strikeMap]);

  const maxOI = useMemo(() => {
    if (!data?.length) return 1;
    return Math.max(...data.map((d) => d.oi), 1);
  }, [data]);

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
              <div className="flex justify-between text-xs text-text-muted mb-2 px-1">
                <span className="text-loss">PE OI</span>
                <span className="text-text-muted">Strike</span>
                <span className="text-profit">CE OI</span>
              </div>
              <div className="space-y-px">
                {strikes.map((strike) => {
                  const entry = strikeMap.get(strike)!;
                  const ceOI = entry.ce?.oi ?? 0;
                  const peOI = entry.pe?.oi ?? 0;
                  const cePct = (ceOI / maxOI) * 45;
                  const pePct = (peOI / maxOI) * 45;
                  return (
                    <div key={strike} className="flex items-center gap-1 h-5">
                      <div className="flex-1 flex justify-end">
                        <div
                          className="h-4 rounded-l bg-red-500/60"
                          style={{ width: `${pePct}%`, minWidth: peOI > 0 ? "2px" : "0" }}
                          title={`PE OI: ${formatOINum(peOI)}`}
                        />
                      </div>
                      <div className="w-20 text-center font-mono text-xs text-text-muted shrink-0">
                        {strike.toLocaleString("en-IN")}
                      </div>
                      <div className="flex-1 flex justify-start">
                        <div
                          className="h-4 rounded-r bg-emerald-500/60"
                          style={{ width: `${cePct}%`, minWidth: ceOI > 0 ? "2px" : "0" }}
                          title={`CE OI: ${formatOINum(ceOI)}`}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
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
                      const ceOI = entry.ce?.oi ?? 0;
                      const peOI = entry.pe?.oi ?? 0;
                      const ceDelta = entry.ce?.oi_delta_d ?? 0;
                      const peDelta = entry.pe?.oi_delta_d ?? 0;
                      const ceLtp = entry.ce?.ltp ?? 0;
                      const peLtp = entry.pe?.ltp ?? 0;
                      const ceSignal = getOIBuildUp(ceOI, ceDelta, ceLtp);
                      const ceColor = OI_BUILDUP_COLORS[ceSignal];
                      return (
                        <TableRow key={strike} className="border-border-default hover:bg-surface-card">
                          <TableCell className="px-2 py-1.5 font-mono text-xs font-semibold text-text-primary">
                            {strike.toLocaleString("en-IN")}
                          </TableCell>
                          <TableCell className="px-2 py-1.5 font-mono text-xs text-profit">{formatOINum(ceOI)}</TableCell>
                          <TableCell className="px-2 py-1.5 font-mono text-xs text-loss">{formatOINum(peOI)}</TableCell>
                          <TableCell className={`px-2 py-1.5 font-mono text-xs ${netColor(ceDelta)}`}>
                            {ceDelta >= 0 ? "+" : ""}{formatOINum(ceDelta)}
                          </TableCell>
                          <TableCell className={`px-2 py-1.5 font-mono text-xs ${netColor(peDelta)}`}>
                            {peDelta >= 0 ? "+" : ""}{formatOINum(peDelta)}
                          </TableCell>
                          <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">
                            {ceLtp > 0 ? ceLtp.toFixed(2) : "--"}
                          </TableCell>
                          <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">
                            {peLtp > 0 ? peLtp.toFixed(2) : "--"}
                          </TableCell>
                          <TableCell className="px-2 py-1.5">
                            <Badge className={`text-xxs h-5 px-1.5 bg-transparent border ${ceColor}`}>
                              {ceSignal}
                            </Badge>
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
