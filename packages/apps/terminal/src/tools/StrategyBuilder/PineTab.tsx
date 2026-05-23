// PineTab — Pine Script editor, backtest runner and results display
// Extracted from StrategyBuilderTool.tsx

import { useState, useMemo, useRef } from "react";
import {
  AlertCircle, Code2, Play, RotateCcw, ChevronDown, ChevronUp, Copy, Check,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePineRunner } from "./usePineRunner";
import type { PineRunnerOptions } from "./usePineRunner";
import { EXCHANGES, INTERVALS, PINE_TEMPLATES } from "./types";
import { computeEquityCurve, computeMetrics } from "./utils";
import { EquityCurveSparkline } from "./EquityCurveSparkline";

export function PineTab() {
  const [code, setCode] = useState(PINE_TEMPLATES.ema_crossover.code);
  const [symbol, setSymbol] = useState("NIFTY");
  const [exchange, setExchange] = useState("NSE_INDEX");
  const [interval, setInterval] = useState("1d");
  const [showTemplates, setShowTemplates] = useState(false);
  const [copied, setCopied] = useState(false);
  const [dateOpts] = useState<PineRunnerOptions>({});
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const { result, bars, isRunning, error, run, reset } = usePineRunner();

  const handleRun = () => {
    void run(code, symbol, exchange, interval, dateOpts);
  };

  const handleReset = () => {
    reset();
  };

  const handleCopyCode = () => {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const handleTemplate = (key: string) => {
    const tmpl = PINE_TEMPLATES[key];
    if (tmpl) {
      setCode(tmpl.code);
      setShowTemplates(false);
      reset();
    }
  };

  const equityCurve = useMemo(
    () => (result && bars.length > 0 ? computeEquityCurve(bars, result.signals) : []),
    [result, bars],
  );

  const metrics = useMemo(
    () => (result && bars.length > 0 ? computeMetrics(bars, result.signals) : null),
    [result, bars],
  );

  const hasErrors = result && result.errors.length > 0;

  return (
    <div className="flex flex-col h-full gap-0 overflow-hidden">
      {/* Symbol / interval config bar */}
      <div className="flex items-center gap-2 px-3 pt-2 pb-1 flex-wrap shrink-0 border-b border-border-subtle">
        <Input
          className="w-24 h-7 text-xs bg-surface-base border-border-default text-text-primary font-mono"
          placeholder="NIFTY"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          aria-label="Symbol"
        />
        <Select value={exchange} onValueChange={setExchange}>
          <SelectTrigger className="w-28 h-7 text-xs bg-surface-base border-border-default text-text-primary" aria-label="Exchange">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default text-text-primary">
            {EXCHANGES.map((ex) => (
              <SelectItem key={ex} value={ex} className="text-xs hover:bg-surface-elevated">{ex}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={interval} onValueChange={setInterval}>
          <SelectTrigger className="w-16 h-7 text-xs bg-surface-base border-border-default text-text-primary" aria-label="Interval">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default text-text-primary">
            {INTERVALS.map((iv) => (
              <SelectItem key={iv} value={iv} className="text-xs hover:bg-surface-elevated">{iv}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="ml-auto flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs border border-border-default text-text-muted hover:text-text-primary hover:bg-surface-elevated"
            onClick={handleCopyCode}
            title="Copy code"
            aria-label="Copy Pine Script code"
          >
            {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs border border-border-default text-text-muted hover:text-text-primary hover:bg-surface-elevated"
            onClick={handleReset}
            title="Clear results"
            aria-label="Clear results"
          >
            <RotateCcw size={11} />
          </Button>
          <Button
            size="sm"
            className="h-7 text-xs bg-primary text-primary-foreground hover:bg-primary/90 font-medium px-3"
            onClick={handleRun}
            disabled={isRunning}
            aria-label="Run Pine Script backtest"
          >
            {isRunning ? (
              <span className="flex items-center gap-1.5">
                <span className="animate-spin inline-block w-2.5 h-2.5 border border-current border-t-transparent rounded-full" aria-hidden="true" />
                Running
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <Play size={10} aria-hidden="true" />
                Run Backtest
              </span>
            )}
          </Button>
        </div>
      </div>

      {/* Template picker */}
      <div className="px-3 py-1 shrink-0 border-b border-border-subtle">
        <button
          className="flex items-center gap-1 text-xs text-text-muted hover:text-text-primary transition-colors"
          onClick={() => setShowTemplates((v) => !v)}
          aria-expanded={showTemplates}
          aria-controls="pine-templates"
        >
          <Code2 size={10} aria-hidden="true" />
          Templates
          {showTemplates ? <ChevronUp size={10} aria-hidden="true" /> : <ChevronDown size={10} aria-hidden="true" />}
        </button>
        {showTemplates && (
          <div id="pine-templates" className="flex flex-wrap gap-1 mt-1.5" role="list">
            {Object.entries(PINE_TEMPLATES).map(([key, tmpl]) => (
              <Button
                key={key}
                variant="ghost"
                size="sm"
                role="listitem"
                className="h-6 px-2 text-xs text-text-muted hover:text-text-primary hover:bg-surface-elevated border border-border-default"
                onClick={() => handleTemplate(key)}
                title={tmpl.description}
              >
                {tmpl.label}
              </Button>
            ))}
          </div>
        )}
      </div>

      {/* Code editor */}
      <div className="flex-1 min-h-0 flex flex-col">
        <textarea
          ref={textareaRef}
          className="flex-1 min-h-0 w-full resize-none bg-surface-base text-text-primary font-mono text-xs p-3 leading-5 border-0 border-b border-border-subtle outline-none focus:ring-1 focus:ring-primary/30 placeholder:text-text-muted"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          spellCheck={false}
          aria-label="Pine Script editor"
          aria-multiline="true"
          role="textbox"
          style={{ tabSize: 4 }}
        />
      </div>

      {/* Results panel */}
      {(result || error) && (
        <div className="shrink-0 max-h-64 overflow-y-auto border-t border-border-default bg-surface-base">
          {/* Top-level API error */}
          {error && (
            <div className="flex items-start gap-2 px-3 py-2 text-xs text-red-400 bg-red-900/10 border-b border-border-subtle">
              <AlertCircle size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span role="alert">{error}</span>
            </div>
          )}

          {/* Pine execution errors (non-fatal warnings) */}
          {hasErrors && (
            <div className="px-3 py-1.5 space-y-0.5 border-b border-border-subtle">
              {result.errors.map((err, i) => (
                <div key={i} className="flex items-start gap-1.5 text-xs text-yellow-400">
                  <AlertCircle size={10} className="mt-0.5 shrink-0" aria-hidden="true" />
                  <span>{err}</span>
                </div>
              ))}
            </div>
          )}

          {result && (
            <>
              {/* Performance metrics */}
              {metrics && (
                <div className="grid grid-cols-5 gap-px bg-border-subtle border-b border-border-default" role="region" aria-label="Performance metrics">
                  {[
                    {
                      label: "Total Return",
                      value: `${metrics.totalReturn >= 0 ? "+" : ""}${(metrics.totalReturn * 100).toFixed(2)}%`,
                      color: metrics.totalReturn >= 0 ? "text-emerald-400" : "text-red-400",
                    },
                    { label: "Signals", value: String(metrics.totalSignals), color: "text-text-primary" },
                    { label: "Buy",     value: String(metrics.buySignals),   color: "text-emerald-400"  },
                    { label: "Sell",    value: String(metrics.sellSignals),  color: "text-red-400"      },
                    {
                      label: "Sharpe~",
                      value: metrics.sharpeApprox.toFixed(2),
                      color: metrics.sharpeApprox >= 1 ? "text-emerald-400" : "text-text-secondary",
                    },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="bg-surface-card px-2 py-2">
                      <div className="text-xxs text-text-muted uppercase tracking-wider">{label}</div>
                      <div className={`text-sm font-mono font-bold tabular-nums ${color}`}>{value}</div>
                    </div>
                  ))}
                </div>
              )}

              {/* Equity curve — inline SVG sparkline */}
              {equityCurve.length >= 2 && (
                <div className="px-3 py-2 border-b border-border-subtle" role="img" aria-label="Equity curve chart">
                  <div className="text-xxs text-text-muted uppercase tracking-wider mb-1">Equity Curve</div>
                  <EquityCurveSparkline curve={equityCurve} />
                </div>
              )}

              {/* Plot legend */}
              {result.plots.length > 0 && (
                <div className="px-3 py-1.5 flex flex-wrap gap-2 border-b border-border-subtle" role="list" aria-label="Plot indicators">
                  {result.plots.map((plot) => (
                    <div key={plot.name} className="flex items-center gap-1" role="listitem">
                      <span
                        className="inline-block w-3 h-0.5 rounded-full"
                        style={{ backgroundColor: plot.color }}
                        aria-hidden="true"
                      />
                      <span className="text-xxs text-text-secondary">{plot.name}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Signals table */}
              {result.signals.length > 0 && (
                <div className="px-0">
                  <div className="text-xxs text-text-muted uppercase tracking-wider px-3 py-1">
                    Signals ({result.signals.length})
                  </div>
                  <div className="max-h-28 overflow-y-auto" role="region" aria-label="Trade signals">
                    <Table>
                      <TableHeader>
                        <TableRow className="border-border-subtle hover:bg-transparent">
                          <TableHead className="text-xxs text-text-muted h-6 pl-3 font-normal">Bar</TableHead>
                          <TableHead className="text-xxs text-text-muted h-6 font-normal">Date</TableHead>
                          <TableHead className="text-xxs text-text-muted h-6 font-normal">Signal</TableHead>
                          <TableHead className="text-xxs text-text-muted h-6 font-normal">Label</TableHead>
                          <TableHead className="text-xxs text-text-muted h-6 text-right pr-3 font-normal">Price</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {result.signals.slice(0, 50).map((sig, idx) => {
                          const bar = bars[sig.bar];
                          const dateStr = bar
                            ? new Date(bar.time * 1000).toLocaleDateString("en-IN", {
                                day: "2-digit",
                                month: "short",
                                year: "2-digit",
                              })
                            : "-";
                          return (
                            <TableRow key={idx} className="border-border-subtle hover:bg-surface-card">
                              <TableCell className="py-0.5 pl-3 text-xxs font-mono text-text-muted">{sig.bar}</TableCell>
                              <TableCell className="py-0.5 text-xxs text-text-secondary">{dateStr}</TableCell>
                              <TableCell className="py-0.5">
                                <Badge
                                  variant="outline"
                                  className={`text-xxs px-1 py-0 border-0 font-mono ${sig.type === "BUY" ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400"}`}
                                >
                                  {sig.type}
                                </Badge>
                              </TableCell>
                              <TableCell className="py-0.5 text-xxs text-text-secondary">{sig.label}</TableCell>
                              <TableCell className="py-0.5 text-xxs font-mono text-right pr-3 text-text-primary">
                                {bar ? bar.close.toFixed(2) : "-"}
                              </TableCell>
                            </TableRow>
                          );
                        })}
                        {result.signals.length > 50 && (
                          <TableRow className="border-border-subtle">
                            <TableCell colSpan={5} className="py-1 pl-3 text-xxs text-text-muted">
                              ... and {result.signals.length - 50} more signals
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              )}

              {result.signals.length === 0 && !error && (
                <div className="px-3 py-3 text-xs text-text-muted">
                  No signals generated. Check your strategy logic or try a different date range / interval.
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
