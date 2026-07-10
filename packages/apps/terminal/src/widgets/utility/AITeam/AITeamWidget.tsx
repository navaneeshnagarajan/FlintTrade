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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, Play, Save, Square, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  getTeamConfig,
  updateTeamConfig,
  runTeamAnalysisStream,
  type AgentRoleConfig,
  type TeamAnalyzeResponse,
  type TeamLifecycleEvent,
  type TeamMode,
} from "@/services/ftApi.ai";

const ROLE_LABELS: Record<AgentRoleConfig["role_type"], string> = {
  technical: "Technical",
  fundamental: "Fundamental",
  sentiment: "Sentiment",
  risk_manager: "Risk",
  aggregator: "Aggregator",
};

const MODE_LABELS: Record<TeamMode, string> = {
  flat: "Flat",
  dag: "DAG",
  sequential: "Sequential",
  debate: "Debate",
};

const DEFAULT_MODES: TeamMode[] = ["flat", "dag", "sequential", "debate"];
const CUSTOM_PRESET = "custom";

function formatName(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatEventType(value: TeamLifecycleEvent["event_type"]): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

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
  const [mode, setMode] = useState<TeamMode>("flat");
  const [selectedPreset, setSelectedPreset] = useState(CUSTOM_PRESET);
  const [result, setResult] = useState<TeamAnalyzeResponse>();
  const [events, setEvents] = useState<TeamLifecycleEvent[]>([]);
  const [analysisError, setAnalysisError] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const runIdRef = useRef(0);

  const configQuery = useQuery({
    queryKey: ["ai", "team", "config"],
    queryFn: getTeamConfig,
  });

  const agents = useMemo(() => {
    const configured = configQuery.data?.agents ?? [];
    if (selectedPreset === CUSTOM_PRESET) {
      return configQuery.data?.custom_agents ?? configured;
    }
    return configured;
  }, [configQuery.data, selectedPreset]);
  const modes = configQuery.data?.modes?.length ? configQuery.data.modes : DEFAULT_MODES;
  const presets = configQuery.data?.presets ?? [];
  const supportsPresets = mode === "flat" || mode === "dag";

  // Mirror the server roster's enabled flags into local toggle state once loaded.
  useEffect(() => {
    if (agents.length) {
      setEnabled(Object.fromEntries(agents.map((a) => [a.name, a.enabled])));
    }
  }, [agents]);

  useEffect(() => {
    setSelectedPreset(configQuery.data?.active_preset || CUSTOM_PRESET);
  }, [configQuery.data?.active_preset]);

  useEffect(
    () => () => {
      runIdRef.current += 1;
      abortControllerRef.current?.abort();
    },
    [],
  );

  const rosterDirty = agents.some((a) => (enabled[a.name] ?? a.enabled) !== a.enabled);
  const customRosterDirty = selectedPreset === CUSTOM_PRESET && rosterDirty;
  const serverPreset = configQuery.data?.active_preset || CUSTOM_PRESET;
  const dirty = rosterDirty || selectedPreset !== serverPreset;

  const save = useMutation({
    mutationFn: () => {
      if (selectedPreset !== CUSTOM_PRESET) return updateTeamConfig({ preset: selectedPreset });
      return updateTeamConfig({
        agents: agents.map((a) => ({ ...a, enabled: enabled[a.name] ?? a.enabled })),
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai", "team", "config"] }),
  });

  const runAnalysis = useCallback(async () => {
    const trimmedSymbol = symbol.trim();
    const trimmedExchange = exchange.trim();
    if (!trimmedSymbol || !trimmedExchange || isRunning) return;

    abortControllerRef.current?.abort();
    const controller = new AbortController();
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;
    abortControllerRef.current = controller;
    setIsRunning(true);
    setAnalysisError("");
    setEvents([]);
    setResult(undefined);

    try {
      const options = {
        mode,
        preset: supportsPresets && selectedPreset !== CUSTOM_PRESET ? selectedPreset : null,
      };
      let receivedResult = false;
      for await (const frame of runTeamAnalysisStream(
        trimmedSymbol,
        trimmedExchange,
        undefined,
        options,
        controller.signal,
      )) {
        if (controller.signal.aborted || runIdRef.current !== runId) break;
        if (frame.type === "event") {
          setEvents((previous) => [...previous, frame.event]);
        } else if (frame.type === "result") {
          receivedResult = true;
          setResult(frame.data);
        } else if (frame.type === "error") {
          throw new Error(frame.message);
        }
      }
      if (!controller.signal.aborted && !receivedResult) {
        throw new Error("Team analysis ended before a result was received.");
      }
    } catch (error) {
      if (!controller.signal.aborted && runIdRef.current === runId) {
        setResult(undefined);
        setAnalysisError(error instanceof Error ? error.message : "Team analysis failed.");
      }
    } finally {
      if (runIdRef.current === runId) {
        abortControllerRef.current = null;
        setIsRunning(false);
      }
    }
  }, [exchange, isRunning, mode, selectedPreset, supportsPresets, symbol]);

  const stopAnalysis = useCallback(() => {
    runIdRef.current += 1;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setIsRunning(false);
  }, []);

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
                  onCheckedChange={(v) => {
                    setEnabled((prev) => ({ ...prev, [a.name]: v }));
                    setSelectedPreset(CUSTOM_PRESET);
                  }}
                  disabled={selectedPreset !== CUSTOM_PRESET}
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
          void runAnalysis();
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
        <div className="flex flex-wrap gap-1" aria-label="Team analysis mode">
          {modes.map((availableMode) => (
            <Button
              key={availableMode}
              type="button"
              size="sm"
              variant={mode === availableMode ? "default" : "outline"}
              className="h-6 px-2 text-xxs"
              aria-pressed={mode === availableMode}
              onClick={() => setMode(availableMode)}
            >
              {MODE_LABELS[availableMode]}
            </Button>
          ))}
        </div>
        <Select
          value={supportsPresets ? selectedPreset : CUSTOM_PRESET}
          onValueChange={setSelectedPreset}
          disabled={!supportsPresets}
        >
          <SelectTrigger className="h-7 w-full text-xs" aria-label="Team preset">
            <SelectValue placeholder="Custom roster" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={CUSTOM_PRESET}>Custom roster</SelectItem>
            {presets.map((preset) => (
              <SelectItem key={preset.name} value={preset.name}>
                {formatName(preset.name)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {isRunning ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={stopAnalysis}
            aria-label="Stop team analysis"
          >
            <Square size={11} className="mr-1" aria-hidden="true" />
            Stop
          </Button>
        ) : (
          <Button
            type="submit"
            size="sm"
            className="h-7 text-xs"
            disabled={!symbol.trim() || !exchange.trim() || customRosterDirty}
            title={customRosterDirty ? "Save the custom roster before analysis" : undefined}
          >
            <Play size={12} className="mr-1" aria-hidden="true" />
            Run team analysis
          </Button>
        )}
        {events.length > 0 && (
          <div
            role="status"
            aria-label="Team analysis progress"
            className="space-y-1 border-t border-border-subtle pt-2"
          >
            {events.map((event, index) => (
              <div
                key={`${event.task_id}:${event.event_type}:${event.timestamp}:${index}`}
                className="flex items-center justify-between gap-2 text-xxs"
              >
                <span className="truncate text-text-secondary">{event.agent_role}</span>
                <span className="flex shrink-0 items-center gap-1 text-text-muted">
                  {event.event_type === "started" && isRunning && (
                    <LoaderCircle size={10} className="animate-spin" aria-hidden="true" />
                  )}
                  {formatEventType(event.event_type)}
                </span>
              </div>
            ))}
          </div>
        )}
        {analysisError && (
          <p className="text-xxs text-loss">
            Analysis failed — configure an LLM provider in Settings, then retry. {analysisError}
          </p>
        )}
        {save.isError && <p className="text-xxs text-loss">Team configuration could not be saved.</p>}
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
