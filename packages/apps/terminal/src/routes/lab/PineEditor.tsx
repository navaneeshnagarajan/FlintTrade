/**
 * Pine Script Indicator Editor — write custom indicators in Pine Script-like
 * syntax and compile them to Python via the FlintTrade backend.
 *
 * v1: Simple textarea editor with template dropdown, compile button, and
 * output panel showing the result or errors.
 */

import { useState, useCallback, useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Brain,
  Code2,
  Play,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Copy,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  compilePineScript,
  type PineCompileResult,
} from "@/services/ftApi";
import { sendPineDraftToBuilder } from "@/tools/StrategyBuilder/pineBridge";

// ---------------------------------------------------------------------------
// Pre-built Pine Script templates
// ---------------------------------------------------------------------------

interface PineTemplate {
  id: string;
  label: string;
  code: string;
}

const PINE_TEMPLATES: PineTemplate[] = [
  {
    id: "sma-cross",
    label: "SMA Crossover",
    code: `//@version=5
indicator("SMA Crossover", overlay=true)
fast_len = input.int(9, "Fast Length")
slow_len = input.int(21, "Slow Length")
fast_sma = ta.sma(close, fast_len)
slow_sma = ta.sma(close, slow_len)
bull = ta.crossover(fast_sma, slow_sma)
bear = ta.crossunder(fast_sma, slow_sma)
plot(fast_sma, color=color.green)
plot(slow_sma, color=color.red)
alertcondition(bull, title="Bullish Cross")`,
  },
  {
    id: "ema-ribbon",
    label: "EMA Ribbon",
    code: `//@version=5
indicator("EMA Ribbon", overlay=true)
ema8  = ta.ema(close, 8)
ema13 = ta.ema(close, 13)
ema21 = ta.ema(close, 21)
ema34 = ta.ema(close, 34)
ema55 = ta.ema(close, 55)
plot(ema8, color=color.green)
plot(ema13, color=color.lime)
plot(ema21, color=color.yellow)
plot(ema34, color=color.orange)
plot(ema55, color=color.red)`,
  },
  {
    id: "rsi-overbought",
    label: "RSI Overbought/Oversold",
    code: `//@version=5
indicator("RSI Signal", overlay=false)
length = input.int(14, "RSI Length")
overbought = input.int(70, "Overbought Level")
oversold = input.int(30, "Oversold Level")
rsi_val = ta.rsi(close, length)
is_overbought = rsi_val > overbought
is_oversold = rsi_val < oversold
plot(rsi_val, color=color.purple)
alertcondition(is_oversold, title="Oversold Signal")
alertcondition(is_overbought, title="Overbought Signal")`,
  },
  {
    id: "macd-signal",
    label: "MACD Signal",
    code: `//@version=5
indicator("MACD Signal", overlay=false)
fast = input.int(12, "Fast Length")
slow = input.int(26, "Slow Length")
signal_len = input.int(9, "Signal Length")
[macd_line, signal_line, hist] = ta.macd(close, fast, slow, signal_len)
bull_cross = ta.crossover(macd_line, signal_line)
bear_cross = ta.crossunder(macd_line, signal_line)
plot(macd_line, color=color.blue)
plot(signal_line, color=color.orange)
alertcondition(bull_cross, title="MACD Bull Cross")`,
  },
  {
    id: "supertrend",
    label: "SuperTrend",
    code: `//@version=5
indicator("SuperTrend", overlay=true)
factor = input.float(3.0, "Factor")
atr_period = input.int(10, "ATR Length")
[st, direction] = ta.supertrend(factor, atr_period)
plot(st, color=color.green)
alertcondition(ta.crossover(close, st), title="Buy Signal")`,
  },
];

// ---------------------------------------------------------------------------
// PineEditor component
// ---------------------------------------------------------------------------

export default function PineEditor() {
  const [code, setCode] = useState<string>(PINE_TEMPLATES[0].code);
  const [copied, setCopied] = useState(false);
  const [sentToBuilder, setSentToBuilder] = useState(false);
  const copiedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copiedTimerRef.current !== null) {
        clearTimeout(copiedTimerRef.current);
      }
      if (sentTimerRef.current !== null) {
        clearTimeout(sentTimerRef.current);
      }
    };
  }, []);

  const compileMutation = useMutation({
    mutationFn: (pineCode: string) => compilePineScript(pineCode),
  });

  const result: PineCompileResult | undefined = compileMutation.data;
  const error = compileMutation.error;

  const handleCompile = useCallback(() => {
    if (code.trim()) {
      compileMutation.mutate(code);
    }
  }, [code, compileMutation]);

  const handleTemplateChange = useCallback((templateId: string) => {
    const template = PINE_TEMPLATES.find((t) => t.id === templateId);
    if (template) {
      setCode(template.code);
      compileMutation.reset();
    }
  }, [compileMutation]);

  // Hand the raw Pine SOURCE (never the compiled Python) to the Strategy
  // Builder's sandboxed interpreter via pineBridge. Compiled Python is a
  // display/copy artefact only — executing it is a deliberate non-goal.
  const handleOpenInBuilder = useCallback(() => {
    if (!sendPineDraftToBuilder({ source: code })) return;
    setSentToBuilder(true);
    if (sentTimerRef.current !== null) {
      clearTimeout(sentTimerRef.current);
    }
    sentTimerRef.current = setTimeout(() => setSentToBuilder(false), 4000);
  }, [code]);

  const handleCopyOutput = useCallback(() => {
    if (result?.python_code) {
      navigator.clipboard.writeText(result.python_code).then(() => {
        setCopied(true);
        copiedTimerRef.current = setTimeout(() => setCopied(false), 2000);
      });
    }
  }, [result]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // Ctrl/Cmd + Enter to compile
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        handleCompile();
      }
      // Tab key inserts spaces instead of moving focus
      if (e.key === "Tab") {
        e.preventDefault();
        const target = e.currentTarget;
        const start = target.selectionStart;
        const end = target.selectionEnd;
        const newValue = code.substring(0, start) + "    " + code.substring(end);
        setCode(newValue);
        // Set cursor position after React re-renders
        requestAnimationFrame(() => {
          target.selectionStart = target.selectionEnd = start + 4;
        });
      }
    },
    [code, handleCompile],
  );

  return (
    <div className="h-full flex flex-col gap-4 p-4 overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-shrink-0">
        <Code2 className="w-5 h-5 text-accent" />
        <h2 className="font-heading font-semibold text-text-primary">
          Pine Script Editor
        </h2>

        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            onClick={handleOpenInBuilder}
            disabled={!code.trim()}
            className="gap-2"
            title="Hand this Pine source to the Strategy Builder's sandboxed interpreter"
          >
            <Brain className="w-4 h-4" />
            Open in Strategy Builder
          </Button>

          <Select onValueChange={handleTemplateChange}>
            <SelectTrigger className="w-52 bg-surface-card border-border-default">
              <SelectValue placeholder="Load template..." />
            </SelectTrigger>
            <SelectContent>
              {PINE_TEMPLATES.map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button
            onClick={handleCompile}
            disabled={compileMutation.isPending || !code.trim()}
            className="gap-2"
          >
            {compileMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            Compile & Apply
          </Button>
        </div>
      </div>

      {/* Hand-off confirmation */}
      {sentToBuilder && (
        <p
          role="status"
          className="flex items-center gap-1.5 text-xs text-emerald-400 flex-shrink-0"
        >
          <CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" />
          Pine source sent — open the Options Builder&apos;s Pine Script tab to run it.
        </p>
      )}

      {/* Editor + Output split */}
      <div className="flex-1 grid grid-cols-2 gap-4 min-h-0">
        {/* Editor panel */}
        <GlassCard className="flex flex-col min-h-0">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border-default">
            <span className="text-xs font-mono text-text-secondary">
              Pine Script
            </span>
            <span className="text-xs text-text-muted">
              Ctrl+Enter to compile
            </span>
          </div>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={handleKeyDown}
            spellCheck={false}
            className="flex-1 w-full resize-none bg-surface-base text-text-primary font-mono text-sm p-3 leading-relaxed focus:outline-none focus:ring-1 focus:ring-accent/30 rounded-b-lg"
            placeholder="Enter Pine Script code here..."
          />
        </GlassCard>

        {/* Output panel */}
        <GlassCard className="flex flex-col min-h-0">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border-default">
            <span className="text-xs font-mono text-text-secondary">
              Python Output
            </span>
            <div className="flex items-center gap-2">
              {result && (
                <>
                  {result.warnings.length > 0 && (
                    <Badge variant="outline" className="text-yellow-400 border-yellow-400/30">
                      <AlertTriangle className="w-3 h-3 mr-1" />
                      {result.warnings.length} warning{result.warnings.length !== 1 ? "s" : ""}
                    </Badge>
                  )}
                  {result.unsupported.length > 0 && (
                    <Badge variant="outline" className="text-orange-400 border-orange-400/30">
                      {result.unsupported.length} unsupported
                    </Badge>
                  )}
                  {result.warnings.length === 0 && result.unsupported.length === 0 && (
                    <Badge variant="outline" className="text-green-400 border-green-400/30">
                      <CheckCircle2 className="w-3 h-3 mr-1" />
                      Success
                    </Badge>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleCopyOutput}
                    className="h-6 px-2 text-xs"
                  >
                    <Copy className="w-3 h-3 mr-1" />
                    {copied ? "Copied" : "Copy"}
                  </Button>
                </>
              )}
            </div>
          </div>

          <ScrollArea className="flex-1">
            <div className="p-3">
              {/* Error state */}
              {error && (
                <div className="flex items-start gap-2 text-red-400 text-sm mb-3">
                  <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <span>{error.message}</span>
                </div>
              )}

              {/* Loading state */}
              {compileMutation.isPending && (
                <div className="flex items-center gap-2 text-text-muted text-sm">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Compiling...</span>
                </div>
              )}

              {/* Result */}
              {result && !compileMutation.isPending && (
                <div className="space-y-4">
                  {/* Imports */}
                  {result.imports.length > 0 && (
                    <div>
                      <p className="text-xs text-text-muted mb-1">Required imports:</p>
                      <pre className="text-xs font-mono text-accent bg-surface-base rounded p-2">
                        {`from packages.indicators.src import ${result.imports.join(", ")}`}
                      </pre>
                    </div>
                  )}

                  {/* Python code (display + copy only — never executed here) */}
                  <p className="text-xs text-text-muted">
                    Compiled Python is for display and copying only — execution happens
                    via the Strategy Builder&apos;s sandboxed Pine interpreter.
                  </p>
                  <pre className="text-sm font-mono text-text-primary bg-surface-base rounded p-3 whitespace-pre-wrap leading-relaxed">
                    {result.python_code}
                  </pre>

                  {/* Warnings */}
                  {result.warnings.length > 0 && (
                    <div className="space-y-1">
                      <p className="text-xs text-yellow-400 font-semibold">Warnings:</p>
                      {result.warnings.map((w: string, i: number) => (
                        <p key={i} className="text-xs text-yellow-400/80 pl-2">
                          - {w}
                        </p>
                      ))}
                    </div>
                  )}

                  {/* Unsupported */}
                  {result.unsupported.length > 0 && (
                    <div className="space-y-1">
                      <p className="text-xs text-orange-400 font-semibold">
                        Unsupported functions:
                      </p>
                      {result.unsupported.map((u: string, i: number) => (
                        <p key={i} className="text-xs text-orange-400/80 pl-2">
                          - {u}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Empty state */}
              {!result && !error && !compileMutation.isPending && (
                <div className="text-center text-text-muted text-sm py-8">
                  <Code2 className="w-8 h-8 mx-auto mb-2 opacity-40" />
                  <p>Write or select a Pine Script template, then click</p>
                  <p className="font-semibold mt-1">Compile & Apply</p>
                  <p className="text-xs mt-2 text-text-muted">
                    Supports 40+ indicators including SMA, EMA, RSI, MACD, SuperTrend, Bollinger Bands and more
                  </p>
                </div>
              )}
            </div>
          </ScrollArea>
        </GlassCard>
      </div>
    </div>
  );
}
