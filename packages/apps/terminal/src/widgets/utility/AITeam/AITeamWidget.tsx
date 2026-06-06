/**
 * AITeamWidget — multi-agent team consensus analysis.
 *
 * Lists the configured specialist agents (technical / fundamental / sentiment /
 * risk-manager + aggregator) from the FlintTrade backend, lets you toggle which
 * are enabled and save, and runs a real team analysis on a symbol via
 * /api/v1/ai/team/*. Each agent's report and the consensus recommendation are
 * real LLM output: when no LLM provider is configured the analysis surfaces a
 * clear "configure in Settings" message rather than fabricating a verdict. The
 * roster always loads (the backend returns the default agents even without an
 * LLM). Read-only / advisory — nothing here touches the gated order path.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Users, Play, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import {
  getTeamConfig,
  updateTeamConfig,
  runTeamAnalysis,
  type AgentRoleConfig,
} from "@/services/ftApi.ai";

const ROLE_LABELS: Record<AgentRoleConfig["role_type"], string> = {
  technical: "Technical",
  fundamental: "Fundamental",
  sentiment: "Sentiment",
  risk_manager: "Risk",
  aggregator: "Aggregator",
};

function signalClass(signal: string): string {
  if (signal === "BUY") return "text-profit";
  if (signal === "SELL") return "text-loss";
  return "text-text-muted";
}

export default function AITeamWidget() {
  const queryClient = useQueryClient();
  const [symbol, setSymbol] = useState("NIFTY");
  const [exchange, setExchange] = useState("NSE_INDEX");
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});

  const configQuery = useQuery({
    queryKey: ["ai", "team", "config"],
    queryFn: getTeamConfig,
  });

  const agents = useMemo(() => configQuery.data?.agents ?? [], [configQuery.data]);

  // Mirror the server roster's enabled flags into local toggle state once loaded.
  useEffect(() => {
    if (agents.length) {
      setEnabled(Object.fromEntries(agents.map((a) => [a.name, a.enabled])));
    }
  }, [agents]);

  const dirty = agents.some((a) => (enabled[a.name] ?? a.enabled) !== a.enabled);

  const save = useMutation({
    mutationFn: () =>
      updateTeamConfig({
        agents: agents.map((a) => ({ ...a, enabled: enabled[a.name] ?? a.enabled })),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai", "team", "config"] }),
  });

  const analysis = useMutation({
    mutationFn: () => runTeamAnalysis(symbol.trim(), exchange.trim()),
  });

  const result = analysis.data;

  return (
    <div className="flex flex-col h-full p-3 gap-3 overflow-y-auto" data-testid="aiteam-widget">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Users size={14} className="text-accent" aria-hidden="true" />
        <span className="text-sm font-semibold text-text-primary">AI Team</span>
      </div>

      {/* Roster */}
      <div className="rounded-lg border border-border-default bg-surface-base p-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xxs uppercase tracking-wide text-text-muted">Specialist agents</span>
          <Button
            size="sm"
            variant="outline"
            className="h-6 px-2 text-xxs"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
            aria-label="Save team configuration"
          >
            <Save size={10} className="mr-1" aria-hidden="true" />
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
        {configQuery.isLoading ? (
          <p className="text-xs text-text-muted py-2">Loading team…</p>
        ) : agents.length === 0 ? (
          <p className="text-xs text-text-muted py-2">No agents configured.</p>
        ) : (
          <ul className="space-y-1.5" aria-label="Team agents">
            {agents.map((a) => (
              <li key={a.name} className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <Badge variant="outline" className="text-xxs shrink-0">
                    {ROLE_LABELS[a.role_type] ?? a.role_type}
                  </Badge>
                  <span className="text-xs text-text-primary truncate">{a.name}</span>
                </div>
                <Switch
                  checked={enabled[a.name] ?? a.enabled}
                  onCheckedChange={(v) => setEnabled((prev) => ({ ...prev, [a.name]: v }))}
                  aria-label={`Toggle ${a.name}`}
                />
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Analysis controls */}
      <form
        className="grid grid-cols-1 gap-2 rounded-lg border border-border-default bg-surface-base p-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (symbol.trim() && exchange.trim()) analysis.mutate();
        }}
      >
        <div className="grid grid-cols-2 gap-2">
          <Input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="Symbol"
            aria-label="Symbol"
            className="h-7 text-xs"
          />
          <Input
            value={exchange}
            onChange={(e) => setExchange(e.target.value)}
            placeholder="Exchange"
            aria-label="Exchange"
            className="h-7 text-xs"
          />
        </div>
        <Button
          type="submit"
          size="sm"
          className="h-7 text-xs"
          disabled={!symbol.trim() || !exchange.trim() || analysis.isPending}
        >
          <Play size={12} className="mr-1" aria-hidden="true" />
          {analysis.isPending ? "Analysing…" : "Run team analysis"}
        </Button>
        {analysis.isError && (
          <p className="text-xxs text-loss">
            Analysis failed — configure an LLM provider in Settings, then retry.
          </p>
        )}
      </form>

      {/* Results */}
      {result && (
        <div className="space-y-2" aria-label="Team analysis result">
          {/* Consensus */}
          <div className="rounded-lg border border-border-default bg-surface-base p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-text-primary">Consensus</span>
              <span className={`text-sm font-bold ${signalClass(result.recommendation.action)}`}>
                {result.recommendation.action}
              </span>
            </div>
            <p className="text-xxs text-text-muted mt-1">
              Confidence {(result.recommendation.confidence * 100).toFixed(0)}% ·{" "}
              {result.recommendation.bullish_count}▲ {result.recommendation.bearish_count}▼{" "}
              {result.recommendation.neutral_count}◦ of {result.recommendation.agent_count}
            </p>
            {result.recommendation.reasoning && (
              <p className="text-xs text-text-secondary mt-2 whitespace-pre-wrap">
                {result.recommendation.reasoning}
              </p>
            )}
          </div>

          {/* Per-agent reports */}
          {(result.analysis.agent_analyses ?? []).map((rep) => (
            <div
              key={rep.agent_name}
              className="rounded-lg border border-border-default bg-surface-base p-3"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-text-primary truncate">{rep.agent_name}</span>
                <span className={`text-xxs font-semibold shrink-0 ${signalClass(rep.signal)}`}>
                  {rep.signal} · {(rep.confidence * 100).toFixed(0)}%
                </span>
              </div>
              {rep.error ? (
                <p className="text-xxs text-loss mt-1">{rep.error}</p>
              ) : (
                <p className="text-xs text-text-secondary mt-1 whitespace-pre-wrap">{rep.report}</p>
              )}
            </div>
          ))}

          {(result.analysis.errors?.length ?? 0) > 0 && (
            <p className="text-xxs text-loss">
              {result.analysis.errors.length} agent error
              {result.analysis.errors.length > 1 ? "s" : ""} during analysis.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
