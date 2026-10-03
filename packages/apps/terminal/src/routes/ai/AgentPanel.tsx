/** Mode-scoped agent control plane with durable, simulated-money Practice evidence. */
import { useEffect, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Loader2, Play, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { useModeStore, type AppMode } from "@/stores/modeStore";
import {
  getAgentStatus, startAgent, stopAgent,
  getPracticeAgentRuns, getPracticeAgentEvents, resolvePracticeAgentRun,
  type AgentSnapshot,
} from "@/services/ftApi";

const ACTIVE_STATES = new Set(["starting", "waiting", "running", "stopping"]);
const TERMINAL_STATES = new Set(["idle", "stopped", "completed", "failed"]);
const EVENT_PAGE_SIZE = 100;
const MODEL_LIMIT_HELP = "Limits cover analysis and reflection calls. The output limit applies per response, not to input tokens. These limits are not a spend guarantee.";
const MODEL_USAGE_LABELS = {
  available: "Available",
  exhausted: "Exhausted",
  evidence_unavailable: "Evidence unavailable",
};

function statusLabel(state: string): string {
  switch (state) {
    case "idle": return "Idle";
    case "starting": return "Starting";
    case "waiting": return "Waiting for market session";
    case "running": return "Running";
    case "stopping": return "Stopping";
    case "stopped": return "Stopped";
    case "completed": return "Completed";
    case "failed": return "Failed";
    case "stop_failed": return "Stop failed";
    case "reconciliation_required": return "Interrupted · reconciliation required";
    default: return `Unknown state: ${state}`;
  }
}

function snapshotState(snapshot?: AgentSnapshot): string {
  const state = (snapshot?.agent_status ?? snapshot?.status ?? (snapshot?.running ? "running" : "idle")).toLowerCase();
  return state === "error" ? "failed" : state;
}

export default function AgentPanel() {
  const appMode = useModeStore((s) => s.mode);
  // Mode changes discard local action/selection state, including late mutation results.
  return <AgentModePanel key={appMode} appMode={appMode} />;
}

function AgentModePanel({ appMode }: { appMode: AppMode }) {
  const queryClient = useQueryClient();
  const isLive = appMode === "live";
  const isPractice = appMode === "practice";
  const enabledMode = isLive || isPractice;
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const [symbols, setSymbols] = useState("RELIANCE");
  const [exchange, setExchange] = useState("NSE");
  const [maxPosition, setMaxPosition] = useState("1");
  const [stopLossPct, setStopLossPct] = useState("2");
  const [takeProfitPct, setTakeProfitPct] = useState("4");
  const [entryRationale, setEntryRationale] = useState("");
  const [modelCallLimit, setModelCallLimit] = useState("500");
  const [modelOutputLimit, setModelOutputLimit] = useState("512");
  const [actionError, setActionError] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const statusKey = ["aiAgent", appMode, "status"] as const;
  const runsKey = ["aiAgent", appMode, "runs"] as const;

  const statusQuery = useQuery({
    queryKey: statusKey,
    queryFn: getAgentStatus,
    enabled: enabledMode,
    refetchInterval: (q) => q.state.data?.running || ACTIVE_STATES.has(snapshotState(q.state.data)) ? 5000 : 15000,
    retry: false,
  });
  // Legacy Live snapshots omit mode; Practice always carries explicit provenance.
  const modeMismatch = !!statusQuery.data && (isPractice
    ? statusQuery.data.mode !== "practice"
    : !!statusQuery.data.mode && statusQuery.data.mode !== appMode);
  const snap = modeMismatch ? undefined : statusQuery.data;
  const state = snapshotState(snap);
  const active = !!snap?.running || ACTIVE_STATES.has(state);
  const positions = Object.entries(snap?.position_details ?? {});
  const unresolvedPositions = !active && (positions.some(([, position]) => position.quantity !== 0)
    || Object.values(snap?.active_positions ?? {}).some((quantity) => quantity !== 0));
  const runsQuery = useQuery({
    queryKey: runsKey,
    queryFn: getPracticeAgentRuns,
    enabled: isPractice,
    refetchInterval: active ? 5000 : 15000,
    retry: false,
  });
  const runs = runsQuery.data ?? [];
  const historyActive = isPractice && runs.some((run) => ACTIVE_STATES.has(run.status));
  const snapshotError = snap?.error || snap?.stop_failure;
  const unresolved = unresolvedPositions || state === "stop_failed" || state === "reconciliation_required" || (isPractice && runs.some((run) => run.status === "reconciliation_required"));
  const selectedRun = runs.find((run) => run.run_id === selectedRunId)
    ?? runs.find((run) => run.status === "reconciliation_required")
    ?? runs.find((run) => run.run_id === snap?.run_id)
    ?? runs[0];
  // A failed terminal write can leave history active after the worker stopped.
  // Only its matching Practice snapshot can establish this recovery path.
  const selectedEvidenceFailed = !!selectedRun && ACTIVE_STATES.has(selectedRun.status)
    && snap?.mode === "practice" && snap.run_id === selectedRun.run_id
    && snap.running === false && state === "reconciliation_required";
  const selectedNeedsReconciliation = selectedRun?.status === "reconciliation_required" || selectedEvidenceFailed;
  const eventsQuery = useInfiniteQuery({
    queryKey: ["aiAgent", appMode, "events", selectedRun?.run_id],
    queryFn: ({ pageParam }) => getPracticeAgentEvents(selectedRun!.run_id, pageParam, EVENT_PAGE_SIZE),
    initialPageParam: 0,
    getNextPageParam: (page) => page.length === EVENT_PAGE_SIZE ? page.at(-1)?.seq : undefined,
    enabled: isPractice && !!selectedRun,
    refetchInterval: selectedRun && ACTIVE_STATES.has(selectedRun.status) ? 5000 : false,
    retry: false,
  });
  const events = eventsQuery.data?.pages.flat() ?? [];
  const evidenceRunId = selectedRun?.run_id;
  const evidenceUpdatedAt = selectedRun?.updated_at;
  const evidenceStatus = selectedRun?.status;
  useEffect(() => {
    if (!isPractice || !evidenceRunId) return;
    // A terminal history update must fetch the final evidence even after polling stops.
    void queryClient.invalidateQueries({ queryKey: ["aiAgent", appMode, "events", evidenceRunId] });
  }, [appMode, isPractice, evidenceRunId, evidenceUpdatedAt, evidenceStatus, queryClient]);

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: statusKey });
    if (isPractice) {
      void queryClient.invalidateQueries({ queryKey: runsKey });
      void queryClient.invalidateQueries({ queryKey: ["aiAgent", appMode, "events"] });
    }
  }
  function onSuccess(snapshot: AgentSnapshot) {
    if (!mounted.current) return;
    setActionError(null);
    // The returned state is immediate evidence; a fresh read follows it.
    queryClient.setQueryData(statusKey, snapshot);
    refresh();
  }
  function onError(err: Error) {
    if (!mounted.current) return;
    setActionError(err.message);
    refresh();
  }
  const startMutation = useMutation({ mutationFn: startAgent, onSuccess, onError });
  const stopMutation = useMutation({ mutationFn: () => stopAgent(true), onSuccess, onError });
  const resolveMutation = useMutation({ mutationFn: resolvePracticeAgentRun, onSuccess, onError });
  const pending = startMutation.isPending || stopMutation.isPending || resolveMutation.isPending;
  const canStart = enabledMode && !!snap?.enabled && statusQuery.isSuccess && !statusQuery.isFetching
    && !modeMismatch && !active && !historyActive && !unresolved && !pending && TERMINAL_STATES.has(state)
    && (!isPractice || (runsQuery.isSuccess && !runsQuery.isFetching));

  function handleStart(e: React.FormEvent) {
    e.preventDefault();
    if (!canStart) return;
    const symbolList = symbols.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
    if (symbolList.length === 0 || symbolList.length > 20) {
      setActionError("Enter between 1 and 20 symbols (comma-separated).");
      return;
    }
    const quantity = Number(maxPosition.trim());
    const stopLoss = Number(stopLossPct.trim());
    const takeProfit = Number(takeProfitPct.trim());
    const positiveDecimal = /^(?:\d+(?:\.\d*)?|\.\d+)$/;
    if (!/^\d+$/.test(maxPosition.trim()) || !Number.isSafeInteger(quantity) || quantity <= 0 || quantity > 1_000_000) {
      setActionError("Maximum position size must be a positive whole number of units, up to 1,000,000.");
      return;
    }
    if (!positiveDecimal.test(stopLossPct.trim()) || !Number.isFinite(stopLoss) || stopLoss <= 0 || stopLoss > 100
      || !positiveDecimal.test(takeProfitPct.trim()) || !Number.isFinite(takeProfit) || takeProfit <= 0 || takeProfit > 100) {
      setActionError("Stop loss and take profit must be positive, finite percentages, up to 100%.");
      return;
    }
    if (!exchange.trim()) {
      setActionError("Enter an exchange.");
      return;
    }
    if (isPractice && entryRationale.trim().length > 2000) {
      setActionError("Operator entry rationale must be at most 2,000 characters.");
      return;
    }
    const callLimit = Number(modelCallLimit.trim());
    const outputLimit = Number(modelOutputLimit.trim());
    if (isPractice && (!/^\d+$/.test(modelCallLimit.trim()) || !Number.isSafeInteger(callLimit) || callLimit < 1 || callLimit > 10_000)) {
      setActionError("Model call limit must be a whole number from 1 to 10,000.");
      return;
    }
    if (isPractice && (!/^\d+$/.test(modelOutputLimit.trim()) || !Number.isSafeInteger(outputLimit) || outputLimit < 16 || outputLimit > 4096)) {
      setActionError("Output tokens per response must be a whole number from 16 to 4,096.");
      return;
    }
    setActionError(null);
    startMutation.mutate({
      symbols: symbolList,
      exchange: exchange.trim().toUpperCase(),
      max_position_size: quantity,
      stop_loss_pct: stopLoss,
      take_profit_pct: takeProfit,
      ...(isPractice ? {
        entry_rationale: entryRationale.trim(), model_call_limit: callLimit, model_output_limit: outputLimit,
      } : {}),
    });
  }

  const badge = !enabledMode ? "Explore" : statusQuery.isError ? "Status unavailable"
    : modeMismatch ? "Mode mismatch" : statusQuery.isPending ? "Checking…" : statusLabel(state);

  return (
    <div className="space-y-4 p-4 max-w-3xl mx-auto">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <Bot size={15} className="text-accent" aria-hidden="true" /> Autonomous Agent
          </h2>
          <p className="text-xs text-text-muted mt-0.5">
            Analyse → signal → risk-check → execute. Every order uses the safety gate.
            Stop requests a square-off; check the resulting state and position evidence.
          </p>
        </div>
        <span role="status" className={cn("text-xxs px-2 py-0.5 rounded-full border", active
          ? "border-profit/30 bg-profit/10 text-profit" : "border-border-subtle bg-text-muted/10 text-text-muted")}>
          {badge}
        </span>
      </div>

      {isPractice && <p className="text-xs text-warning bg-warning/10 border border-warning/30 rounded px-2.5 py-1.5">
        Practice · simulated money. Uses sandbox fills and configured market data; results do not establish Live readiness.
      </p>}
      {isLive && <p className="text-xs text-warning">Live · real money. Existing PIN, account authorisation and approval requirements still apply.</p>}
      {!enabledMode && <p className="text-xs text-text-muted">Explore cannot run an agent. Switch to Practice or Live to start a session.</p>}
      {snap && !snap.enabled && <p className="text-xs text-warning bg-warning/10 border border-warning/30 rounded px-2.5 py-1.5">
        The autonomous agent is disabled. Enable it deliberately via <code className="font-mono">ai.autonomous_agent.enabled</code> in workspace.json.
        {isLive && <> Grant the <code className="font-mono">autonomous-trader</code> actor access in <code className="font-mono">brokers.account_acls</code>.</>}
      </p>}
      {statusQuery.isError && <p role="alert" className="text-xs text-loss">Unable to check agent status: {statusQuery.error.message}. Starts remain blocked until status is known.</p>}
      {modeMismatch && <p role="alert" className="text-xs text-loss">The server session mode differs from {appMode}. Refresh the authenticated session before starting.</p>}
      {unresolved && <p className="text-xs text-warning">An interrupted run needs reconciliation. There is no automatic replay. Check the {isPractice ? "Practice" : "Live"} account and evidence before starting again.</p>}
      {historyActive && !active && <p className="text-xs text-warning">Practice history still reports an active run. Refresh status before starting another session.</p>}
      {snapshotError && <p role="alert" className="text-xs text-loss">{snapshotError}</p>}
      {actionError && actionError !== snapshotError && <p role="alert" className="text-xs text-loss">{actionError}</p>}

      {!active && <GlassCard className="p-4 space-y-2">
        <h3 className="text-xs font-semibold text-text-primary">Start a session</h3>
        <form className="space-y-2" onSubmit={handleStart}>
          <Input value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="Symbols, comma-separated (e.g. RELIANCE, ICICIBANK)" aria-label="Agent symbols" className="h-7 text-xs font-mono" />
          <div className="flex flex-wrap items-center gap-2">
            <Input value={exchange} onChange={(e) => setExchange(e.target.value)} aria-label="Agent exchange" className="h-7 w-20 text-xs" />
            <Input value={maxPosition} onChange={(e) => setMaxPosition(e.target.value)} aria-label="Maximum position size in units" title="Maximum position size (units)" inputMode="numeric" className="h-7 w-16 text-xs font-mono" />
            <Input value={stopLossPct} onChange={(e) => setStopLossPct(e.target.value)} aria-label="Stop loss percent" title="Stop-loss %" inputMode="decimal" className="h-7 w-16 text-xs font-mono" />
            <Input value={takeProfitPct} onChange={(e) => setTakeProfitPct(e.target.value)} aria-label="Take profit percent" title="Take-profit %" inputMode="decimal" className="h-7 w-16 text-xs font-mono" />
            <Button type="submit" size="sm" disabled={!canStart} className="gap-1.5 h-7">
              {startMutation.isPending ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Play size={13} aria-hidden="true" />}
              Start agent
            </Button>
          </div>
          <p className="text-xxs text-text-muted">Units · SL% · TP%. The daily-loss limit blocks new entries while existing positions remain supervised.</p>
          {isPractice && <fieldset className="space-y-1.5">
            <legend className="text-xs font-semibold text-text-primary">Practice model limits</legend>
            <div className="flex flex-wrap gap-3">
              <div className="space-y-1">
                <label htmlFor="agent-model-call-limit" className="block text-xs text-text-secondary">Model call limit</label>
                <Input id="agent-model-call-limit" value={modelCallLimit} onChange={(e) => setModelCallLimit(e.target.value)} inputMode="numeric" aria-describedby="agent-model-call-range agent-model-limit-help" className="h-7 w-28 text-xs font-mono" />
                <p id="agent-model-call-range" className="text-xxs text-text-muted">1–10,000 calls per run</p>
              </div>
              <div className="space-y-1">
                <label htmlFor="agent-model-output-limit" className="block text-xs text-text-secondary">Output tokens per response</label>
                <Input id="agent-model-output-limit" value={modelOutputLimit} onChange={(e) => setModelOutputLimit(e.target.value)} inputMode="numeric" aria-describedby="agent-model-output-range agent-model-limit-help" className="h-7 w-28 text-xs font-mono" />
                <p id="agent-model-output-range" className="text-xxs text-text-muted">16–4,096 output tokens</p>
              </div>
            </div>
            <p id="agent-model-limit-help" className="text-xxs text-text-muted">{MODEL_LIMIT_HELP}</p>
          </fieldset>}
          {isPractice && <div className="space-y-1">
            <label htmlFor="agent-entry-rationale" className="block text-xs text-text-secondary">Operator entry rationale (optional)</label>
            <Textarea id="agent-entry-rationale" value={entryRationale} onChange={(e) => setEntryRationale(e.target.value)} maxLength={2000} aria-describedby="agent-entry-rationale-help" className="text-xs" />
            <p id="agent-entry-rationale-help" className="text-xxs text-text-muted">
              Your session plan is stored with this Practice run and passed to admission for each entry. Laya still decides every entry; the agent does not automatically accept clamps.
              Do not include credentials or secrets. Maximum 2,000 characters.
            </p>
          </div>}
        </form>
      </GlassCard>}

      {snap && (active || positions.length > 0 || snap.run_id) && <GlassCard className="p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-secondary">
          <span>{isPractice ? "Simulated day P&L" : "Day P&L"} <span className={cn("font-mono", (snap.daily_pnl ?? 0) >= 0 ? "text-profit" : "text-loss")}>{snap.daily_pnl?.toFixed(0) ?? "—"}</span></span>
          <span>Cycles <span className="font-mono">{snap.cycle_count ?? "—"}</span></span>
          <span className="font-mono text-text-muted">{(snap.params?.symbols as string[] | undefined)?.join(", ")}</span>
          {active && <Button size="sm" variant="outline" onClick={() => stopMutation.mutate()} disabled={pending || state === "stopping"} className="gap-1.5 h-6 text-xxs ml-auto">
            {stopMutation.isPending ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : <Square size={12} aria-hidden="true" />}
            Stop &amp; square off
          </Button>}
        </div>
        {statusQuery.isError && <p className="text-xs text-warning">Last known session evidence. Current state could not be refreshed.</p>}
        {isPractice && <section aria-label="Practice model usage" className="space-y-1 text-xs text-text-secondary">
          <h3 className="font-semibold text-text-primary">Practice model usage</h3>
          {snap.model_usage ? <>
            <p className={snap.model_usage.status === "available" ? "text-text-secondary" : "text-warning"}>
              Budget status: {MODEL_USAGE_LABELS[snap.model_usage.status]}
            </p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono">
              <span>{snap.model_usage.model_calls_used} / {snap.model_usage.model_call_limit} model calls used</span>
              <span>{snap.model_usage.model_calls_remaining} model calls remaining</span>
              <span>{snap.model_usage.model_output_limit} output tokens per response</span>
            </div>
            <p className="text-xxs text-text-muted">{MODEL_LIMIT_HELP}</p>
          </> : <p className="text-text-muted">Model usage evidence is unavailable for this run.</p>}
        </section>}
        {positions.length === 0 ? <p className="text-xs text-text-muted">No open agent positions reported.</p> : <div className="overflow-x-auto">
          <table className="w-full text-xxs" aria-label="Agent positions">
            <thead><tr className="text-text-muted border-b border-border-subtle">
              <th className="text-left py-1 font-normal">Symbol</th><th className="text-left py-1 font-normal">Side</th>
              <th className="text-right py-1 font-normal">Units</th><th className="text-right py-1 font-normal">Entry</th>
              <th className="text-right py-1 font-normal">SL</th><th className="text-right py-1 font-normal">TP</th>
            </tr></thead>
            <tbody>{positions.map(([symbol, d]) => <tr key={symbol} className="border-b border-border-subtle/50">
              <td className="py-1 font-mono text-text-primary">{symbol}</td>
              <td className={cn("py-1", d.action === "BUY" ? "text-profit" : "text-loss")}>{d.action}</td>
              <td className="py-1 text-right font-mono">{d.quantity}</td><td className="py-1 text-right font-mono">{d.entry_price.toFixed(2)}</td>
              <td className="py-1 text-right font-mono">{d.stop_loss.toFixed(2)}</td><td className="py-1 text-right font-mono">{d.take_profit.toFixed(2)}</td>
            </tr>)}</tbody>
          </table>
        </div>}
      </GlassCard>}

      {isPractice && <GlassCard className="p-4 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-xs font-semibold text-text-primary">Practice run history</h3>
          <Button size="sm" variant="outline" onClick={refresh} disabled={runsQuery.isFetching || statusQuery.isFetching} className="h-6 text-xxs">Refresh</Button>
        </div>
        {runsQuery.isPending && <p className="text-xs text-text-muted">Loading Practice runs…</p>}
        {runsQuery.isError && <p role="alert" className="text-xs text-loss">Unable to load Practice history: {runsQuery.error.message}</p>}
        {runsQuery.isSuccess && runs.length === 0 && <p className="text-xs text-text-muted">No Practice runs recorded.</p>}
        {selectedRun && <>
          <label className="block text-xs text-text-secondary">Practice run
            <select aria-label="Practice run" value={selectedRun.run_id} onChange={(e) => { setSelectedRunId(e.target.value); setActionError(null); }} className="block mt-1 w-full min-w-0 rounded border border-border-subtle bg-surface-base p-1.5 font-mono text-xs">
              {runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.created_at} · {statusLabel(run.status)} · {run.run_id}</option>)}
            </select>
          </label>
          <p className="text-xs text-text-muted break-all">Run {selectedRun.run_id} · {statusLabel(selectedRun.status)} · Updated {selectedRun.updated_at}</p>
          {typeof selectedRun.config.entry_rationale === "string" && selectedRun.config.entry_rationale && <div className="text-xs text-text-secondary">
            <p className="font-semibold">Saved operator entry rationale</p>
            <p className="whitespace-pre-wrap break-words">{selectedRun.config.entry_rationale}</p>
          </div>}
          {selectedRun.error && selectedRun.error !== snapshotError && <p role="alert" className="text-xs text-loss">{selectedRun.error}</p>}
          {selectedNeedsReconciliation && <div className="space-y-2">
            <p className="text-xs text-warning">The server verifies the Practice account is flat before resolving. Resolution does not restart this run or repeat any orders.</p>
            <Button size="sm" variant="outline" disabled={pending || active || statusQuery.isError || !snap || runsQuery.isError} onClick={() => resolveMutation.mutate(selectedRun.run_id)}>Resolve interrupted run</Button>
          </div>}
          <h4 className="text-xs font-semibold text-text-primary">Run events</h4>
          {eventsQuery.isPending && <p className="text-xs text-text-muted">Loading run events…</p>}
          {eventsQuery.isError && <p role="alert" className="text-xs text-loss">Unable to load run events: {eventsQuery.error.message}</p>}
          {eventsQuery.isSuccess && events.length === 0 && <p className="text-xs text-text-muted">No events recorded for this run.</p>}
          {events.length > 0 && <ol aria-label="Practice run events" className="max-h-80 overflow-auto space-y-2">
            {events.map((event) => <li key={`${event.run_id}:${event.seq}`} className="rounded border border-border-subtle p-2 text-xxs">
              <p className="font-mono text-text-secondary break-all">#{event.seq} · {event.kind} · {event.created_at}</p>
              <pre className="mt-1 whitespace-pre-wrap break-all text-text-muted">{JSON.stringify(event.data, null, 2)}</pre>
            </li>)}
          </ol>}
          {eventsQuery.hasNextPage && <Button size="sm" variant="outline" disabled={eventsQuery.isFetching} onClick={() => void eventsQuery.fetchNextPage()}>Load more events</Button>}
        </>}
      </GlassCard>}
    </div>
  );
}
