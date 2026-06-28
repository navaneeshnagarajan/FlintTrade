/**
 * AgentPanel — control plane for the AI agent session.
 *
 * Drives /api/v1/ai/agent/{start,stop,status}. Honest by construction:
 *   - The feature is OFF by default; the backend's actionable refusal
 *     messages (enable flag, live mode, PIN, ACL grant) surface verbatim.
 *   - The agent runs as its own principal ("autonomous-trader") — the
 *     operator must grant it account access in workspace.json; the panel
 *     shows that exact instruction when the backend refuses.
 *   - All session figures (P&L, cycles, positions) are live backend state,
 *     polled while running. Nothing is fabricated when idle.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Loader2, Play, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { useModeStore } from "@/stores/modeStore";
import { getAgentStatus, startAgent, stopAgent } from "@/services/ftApi";

export default function AgentPanel() {
  const queryClient = useQueryClient();
  const appMode = useModeStore((s) => s.mode);
  const isLive = appMode === "live";

  const [symbols, setSymbols] = useState("RELIANCE");
  const [exchange, setExchange] = useState("NSE");
  const [maxPosition, setMaxPosition] = useState("1");
  const [stopLossPct, setStopLossPct] = useState("2");
  const [takeProfitPct, setTakeProfitPct] = useState("4");
  const [actionError, setActionError] = useState<string | null>(null);

  const statusQuery = useQuery({
    queryKey: ["aiAgent", "status"],
    queryFn: getAgentStatus,
    refetchInterval: (q) => (q.state.data?.running ? 5000 : false),
    retry: false,
  });
  const snap = statusQuery.data;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["aiAgent", "status"] });

  const startMutation = useMutation({
    mutationFn: startAgent,
    onSuccess: () => {
      setActionError(null);
      refresh();
    },
    onError: (err: Error) => setActionError(err.message),
  });

  const stopMutation = useMutation({
    mutationFn: () => stopAgent(true),
    onSuccess: () => {
      setActionError(null);
      refresh();
    },
    onError: (err: Error) => setActionError(err.message),
  });

  function handleStart(e: React.FormEvent) {
    e.preventDefault();
    const symbolList = symbols
      .split(",")
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    if (symbolList.length === 0) {
      setActionError("Enter at least one symbol (comma-separated).");
      return;
    }
    startMutation.mutate({
      symbols: symbolList,
      exchange: exchange.trim().toUpperCase() || "NSE",
      max_position_size: Number.parseInt(maxPosition, 10) || 1,
      stop_loss_pct: Number.parseFloat(stopLossPct) || 2,
      take_profit_pct: Number.parseFloat(takeProfitPct) || 4,
    });
  }

  const positions = Object.entries(snap?.position_details ?? {});

  return (
    <div className="space-y-4 p-4 max-w-3xl mx-auto">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <Bot size={15} className="text-accent" aria-hidden="true" />
            Autonomous Agent
          </h2>
          <p className="text-xs text-text-muted mt-0.5">
            An LLM-driven session loop: analyse → signal → risk-check → execute. Every
            order runs the full safety gate; the agent trades as its own authorised
            principal and squares off on stop.
          </p>
        </div>
        <span
          className={cn(
            "text-xxs px-2 py-0.5 rounded-full border",
            snap?.running
              ? "border-profit/30 bg-profit/10 text-profit"
              : "border-border-subtle bg-text-muted/10 text-text-muted",
          )}
        >
          {statusQuery.isLoading ? "Checking…" : snap?.running ? "Running" : "Idle"}
        </span>
      </div>

      {snap && !snap.enabled && (
        <p className="text-xs text-warning bg-warning/10 border border-warning/30 rounded px-2.5 py-1.5">
          The autonomous agent is disabled. It places real orders in live mode —
          enable it deliberately via{" "}
          <code className="font-mono">ai.autonomous_agent.enabled</code> in
          workspace.json, and grant the{" "}
          <code className="font-mono">autonomous-trader</code> actor access in{" "}
          <code className="font-mono">brokers.account_acls</code>.
        </p>
      )}

      {!isLive && (
        <p className="text-xs text-text-muted">
          The agent trades live only — switch to Live mode to start a session.
        </p>
      )}

      {/* Start form */}
      {!snap?.running && (
        <GlassCard className="p-4 space-y-2">
          <h3 className="text-xs font-semibold text-text-primary">Start a session</h3>
          <form className="space-y-2" onSubmit={handleStart}>
            <Input
              value={symbols}
              onChange={(e) => setSymbols(e.target.value)}
              placeholder="Symbols, comma-separated (e.g. RELIANCE, ICICIBANK)"
              aria-label="Agent symbols"
              className="h-7 text-xs font-mono"
            />
            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={exchange}
                onChange={(e) => setExchange(e.target.value)}
                aria-label="Agent exchange"
                className="h-7 w-20 text-xs"
              />
              <Input
                value={maxPosition}
                onChange={(e) => setMaxPosition(e.target.value)}
                aria-label="Maximum position size in lots"
                title="Maximum position size (lots)"
                inputMode="numeric"
                className="h-7 w-16 text-xs font-mono"
              />
              <Input
                value={stopLossPct}
                onChange={(e) => setStopLossPct(e.target.value)}
                aria-label="Stop loss percent"
                title="Stop-loss %"
                inputMode="decimal"
                className="h-7 w-16 text-xs font-mono"
              />
              <Input
                value={takeProfitPct}
                onChange={(e) => setTakeProfitPct(e.target.value)}
                aria-label="Take profit percent"
                title="Take-profit %"
                inputMode="decimal"
                className="h-7 w-16 text-xs font-mono"
              />
              <Button
                type="submit"
                size="sm"
                disabled={!isLive || startMutation.isPending}
                className="gap-1.5 h-7"
              >
                {startMutation.isPending ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Play size={13} />
                )}
                Start agent
              </Button>
            </div>
            <p className="text-xxs text-text-muted">
              Lots · SL% · TP% — the session also stops itself at the daily loss
              limit and squares off before market close.
            </p>
          </form>
        </GlassCard>
      )}

      {actionError && (
        <p role="alert" className="text-xs text-loss">
          {actionError}
        </p>
      )}

      {/* Running session */}
      {snap?.running && (
        <GlassCard className="p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-secondary">
            <span>
              Day P&L{" "}
              <span
                className={cn(
                  "font-mono",
                  (snap.daily_pnl ?? 0) >= 0 ? "text-profit" : "text-loss",
                )}
              >
                {(snap.daily_pnl ?? 0).toFixed(0)}
              </span>
            </span>
            <span>Cycles <span className="font-mono">{snap.cycle_count ?? 0}</span></span>
            <span className="font-mono text-text-muted">
              {(snap.params?.symbols as string[] | undefined)?.join(", ")}
            </span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => stopMutation.mutate()}
              disabled={stopMutation.isPending}
              className="gap-1.5 h-6 text-xxs ml-auto"
            >
              {stopMutation.isPending ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Square size={12} />
              )}
              Stop &amp; square off
            </Button>
          </div>

          {positions.length === 0 ? (
            <p className="text-xs text-text-muted">No open agent positions.</p>
          ) : (
            <table className="w-full text-xxs" aria-label="Agent positions">
              <thead>
                <tr className="text-text-muted border-b border-border-subtle">
                  <th className="text-left py-1 font-normal">Symbol</th>
                  <th className="text-left py-1 font-normal">Side</th>
                  <th className="text-right py-1 font-normal">Qty</th>
                  <th className="text-right py-1 font-normal">Entry</th>
                  <th className="text-right py-1 font-normal">SL</th>
                  <th className="text-right py-1 font-normal">TP</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(([symbol, d]) => (
                  <tr key={symbol} className="border-b border-border-subtle/50">
                    <td className="py-1 font-mono text-text-primary">{symbol}</td>
                    <td className={cn("py-1", d.action === "BUY" ? "text-profit" : "text-loss")}>
                      {d.action}
                    </td>
                    <td className="py-1 text-right font-mono">{d.quantity}</td>
                    <td className="py-1 text-right font-mono">{d.entry_price.toFixed(2)}</td>
                    <td className="py-1 text-right font-mono">{d.stop_loss.toFixed(2)}</td>
                    <td className="py-1 text-right font-mono">{d.take_profit.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </GlassCard>
      )}
    </div>
  );
}
