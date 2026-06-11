/**
 * ConditionScannerWidget — declarative market scanner over /ft-api/v1/scanner/*.
 *
 * Runs the backend's prebuilt condition scans (RSI oversold/overbought, volume
 * spikes, EMA crosses, …) across a symbol universe and lists the matches with
 * matched conditions and a composite score. Distinct from the pre-market
 * Scanner dashboard widget: this consumes the screener's declarative
 * MarketScanner engine, whose results are condition matches, not market movers.
 *
 * Honesty: the run response itself carries ``is_sample_data`` — the backend
 * scans live broker OHLCV when a broker is connected, deterministic synthetic
 * bars otherwise — so the Live/Sample badge reflects what the backend actually
 * scanned, not a connection guess.
 */

import { useState, memo } from "react";
import { Radar, Loader2, Play } from "lucide-react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  getPrebuiltScans,
  runPrebuiltScan,
  type ScannerRunResponse,
} from "@/services/ftApi";

function ConditionScannerWidget() {
  const [scanKey, setScanKey] = useState<string>("");

  const prebuiltQuery = useQuery({
    queryKey: ["scannerPrebuilt"],
    queryFn: getPrebuiltScans,
  });
  const scans = prebuiltQuery.data?.scans ?? [];

  const runMutation = useMutation<ScannerRunResponse, Error, string>({
    mutationFn: runPrebuiltScan,
  });
  const run = runMutation.data;

  const selectedScan = scans.find((s) => s.key === scanKey);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Radar size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Condition Scanner</span>
        {run && (
          run.is_sample_data ? (
            <span
              className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
              role="status"
              aria-label="Scan ran on sample data; connect a broker to scan live prices"
              title="The backend scanned deterministic sample bars — connect a broker to scan live OHLCV."
            >
              Sample data
            </span>
          ) : (
            <span
              className="inline-flex items-center rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400"
              role="status"
              aria-label="Scan ran on live broker data"
              title="Live — the backend scanned real OHLCV from the connected broker."
            >
              Live
            </span>
          )
        )}
        <div className="flex-1" />
        <Select value={scanKey} onValueChange={setScanKey}>
          <SelectTrigger
            className="h-7 w-48 text-xs bg-surface-hover border-border-default text-text-primary"
            aria-label="Prebuilt scan"
          >
            <SelectValue placeholder={prebuiltQuery.isLoading ? "Loading scans…" : "Choose a scan"} />
          </SelectTrigger>
          <SelectContent>
            {scans.map((s) => (
              <SelectItem key={s.key} value={s.key} className="text-xs">
                {s.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          size="sm"
          onClick={() => scanKey && runMutation.mutate(scanKey)}
          disabled={!scanKey || runMutation.isPending}
          className="h-7 px-3 text-xs"
        >
          {runMutation.isPending
            ? <Loader2 size={12} className="animate-spin mr-1" aria-hidden="true" />
            : <Play size={11} className="mr-1" aria-hidden="true" />}
          Run
        </Button>
      </div>

      {/* Selected-scan conditions */}
      {selectedScan && (
        <div className="flex-none px-2 py-1.5 bg-surface-elevated border-b border-border-subtle flex items-center gap-1.5 flex-wrap">
          <span className="text-xxs text-text-muted uppercase tracking-wide">
            {selectedScan.universe} · {selectedScan.timeframe}
          </span>
          {selectedScan.conditions.map((c) => (
            <span
              key={c.label}
              className="inline-flex items-center rounded border border-border-default px-1.5 py-0.5 text-xxs text-text-secondary"
              title={`${c.indicator} ${c.operator} ${c.value}`}
            >
              {c.label}
            </span>
          ))}
        </div>
      )}

      {/* Results */}
      <div className="flex-1 min-h-0 overflow-auto">
        {prebuiltQuery.isError && (
          <p className="text-xs text-loss text-center py-8">
            Failed to load scans. Backend may be offline.
          </p>
        )}
        {runMutation.isError && (
          <p className="text-xs text-loss text-center py-8">
            Scan failed: {runMutation.error.message}
          </p>
        )}
        {!run && !runMutation.isError && !prebuiltQuery.isError && (
          <p className="text-xs text-text-muted text-center py-8">
            Choose a prebuilt scan and press Run to screen the universe.
          </p>
        )}
        {run && run.results.length === 0 && (
          <p className="text-xs text-text-muted text-center py-8">
            No symbols matched “{run.scan_name}” ({run.total_universe} scanned).
          </p>
        )}
        {run && run.results.length > 0 && (
          <>
            <div className="text-xxs text-text-muted px-2 pt-1.5">
              {run.matched_count} of {run.total_universe} matched · {run.scan_name}
            </div>
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  <TableHead className="text-xxs text-text-muted font-medium">Symbol</TableHead>
                  <TableHead className="text-xxs text-text-muted font-medium text-right">LTP</TableHead>
                  <TableHead className="text-xxs text-text-muted font-medium text-right">Chg %</TableHead>
                  <TableHead className="text-xxs text-text-muted font-medium">Matched</TableHead>
                  <TableHead className="text-xxs text-text-muted font-medium text-right">Score</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {run.results.map((r) => (
                  <TableRow key={r.symbol} className="border-border-subtle hover:bg-surface-hover">
                    <TableCell className="text-xs font-mono text-text-primary py-1">
                      {r.symbol}
                      <span className="text-text-muted"> · {r.exchange}</span>
                    </TableCell>
                    <TableCell className="text-xs font-mono py-1 text-right tabular-nums text-text-secondary">
                      {r.ltp.toLocaleString("en-IN")}
                    </TableCell>
                    <TableCell className={`text-xs font-mono py-1 text-right tabular-nums ${r.change_pct >= 0 ? "text-profit" : "text-loss"}`}>
                      {r.change_pct >= 0 ? "+" : ""}{r.change_pct.toFixed(2)}%
                    </TableCell>
                    <TableCell className="text-xxs text-text-secondary py-1">
                      {r.matched_conditions.join(", ")}
                    </TableCell>
                    <TableCell className="text-xs font-mono py-1 text-right tabular-nums text-text-secondary">
                      {r.score.toFixed(2)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </div>
    </div>
  );
}

export default memo(ConditionScannerWidget);
