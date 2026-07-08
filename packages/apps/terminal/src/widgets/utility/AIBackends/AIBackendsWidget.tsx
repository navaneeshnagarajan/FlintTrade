/**
 * AIBackendsWidget — catalogue of supported AI backends and a streaming runner.
 *
 * Consumes the backend's honest agent-backend registry (GET /ai/agents/backends)
 * and lists every backend badged by kind and live detection status:
 *
 *   - LLM chat/completion providers (claude-code, claude-code-oauth, cerebras)
 *     are configured in Settings and driven through the AI Advisor — they show
 *     their config status and point to Settings, never a run box.
 *   - CLI/ACP agent runtimes (codex, antigravity, hermes) are detected by their
 *     binary on PATH. A runnable one gets a prompt box; Run streams the agent's
 *     Server-Sent AgentEvents into a live output pane (output text is appended,
 *     tool and error frames render distinctly, and the stream stops on `done`).
 *
 * Every state is honest: a not-installed agent shows an install hint, an
 * unconfigured LLM points to Settings, and nothing is ever fabricated.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  Loader2,
  MessageSquare,
  Play,
  RefreshCw,
  Settings,
  Square,
  Terminal,
  Wrench,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  getAgentBackends,
  runAgent,
  type AgentEvent,
  type BackendItem,
  type BackendKind,
  type BackendStatus,
} from "@/services/ftApi.ai";

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------

const STATUS_META: Record<BackendStatus, { label: string; className: string }> = {
  ready: { label: "Ready", className: "border-profit/30 bg-profit/10 text-profit" },
  installed: { label: "Installed", className: "border-accent/30 bg-accent/10 text-accent" },
  needs_config: { label: "Needs config", className: "border-warning/30 bg-warning/10 text-warning" },
  not_installed: { label: "Not installed", className: "border-border-default bg-text-muted/10 text-text-muted" },
};

function kindLabel(kind: BackendKind): string {
  switch (kind) {
    case "llm":
      return "LLM";
    case "cli_agent":
      return "CLI agent";
    case "acp_agent":
      return "ACP agent";
  }
}

/** An agent runtime is runnable when its binary is present (ready/installed). */
function isRunnable(backend: BackendItem): boolean {
  return backend.requires_binary && backend.status !== "not_installed";
}

function openSettings(): void {
  window.dispatchEvent(new CustomEvent("flinttrade:navigate", { detail: "/settings" }));
}

// ---------------------------------------------------------------------------
// Streamed event rendering
// ---------------------------------------------------------------------------

function AgentEventLine({ event }: { event: AgentEvent }) {
  if (event.kind === "output") {
    return (
      <span className="whitespace-pre-wrap font-mono text-text-secondary">{event.text}</span>
    );
  }
  if (event.kind === "tool") {
    return (
      <div className="my-1 flex items-start gap-1.5 rounded border border-accent/30 bg-accent/5 px-2 py-1 text-accent">
        <Wrench size={11} className="mt-0.5 shrink-0" aria-hidden="true" />
        <span className="break-all font-mono">
          {event.text ?? (event.data ? JSON.stringify(event.data) : "Tool call")}
        </span>
      </div>
    );
  }
  if (event.kind === "error") {
    return (
      <div
        role="alert"
        className="my-1 flex items-start gap-1.5 rounded border border-loss/30 bg-loss/5 px-2 py-1 text-loss"
      >
        <AlertCircle size={11} className="mt-0.5 shrink-0" aria-hidden="true" />
        <span className="break-words">{event.text ?? "The agent reported an error."}</span>
      </div>
    );
  }
  // done
  return (
    <div className="mt-1 flex items-center gap-1 text-xxs text-text-muted">
      <CheckCircle2 size={11} className="text-profit" aria-hidden="true" /> Completed
    </div>
  );
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------

export default function AIBackendsWidget() {
  const backendsQuery = useQuery({
    queryKey: ["ai", "agent-backends"],
    queryFn: getAgentBackends,
    refetchInterval: 60_000,
    retry: false,
  });

  const [activeId, setActiveId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Abort any in-flight stream when the widget unmounts.
  useEffect(() => () => abortRef.current?.abort(), []);

  const resetRunState = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setEvents([]);
    setRunError(null);
    setRunning(false);
  }, []);

  const toggleRun = useCallback(
    (id: string) => {
      resetRunState();
      setPrompt("");
      setActiveId((current) => (current === id ? null : id));
    },
    [resetRunState],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setRunning(false);
  }, []);

  const start = useCallback(
    async (id: string) => {
      const text = prompt.trim();
      if (!text || running) return;

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setRunning(true);
      setRunError(null);
      setEvents([]);

      try {
        for await (const event of runAgent(id, text, controller.signal)) {
          setEvents((prev) => [...prev, event]);
          if (event.kind === "done") break;
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          setRunError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
          setRunning(false);
        }
      }
    },
    [prompt, running],
  );

  const backends = backendsQuery.data?.backends ?? [];
  const llmBackends = backends.filter((b) => b.kind === "llm");
  const agentBackends = backends.filter((b) => b.kind !== "llm");

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3" data-testid="ai-backends-widget">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Cpu size={14} className="text-accent" aria-hidden="true" />
          <span className="text-sm font-semibold text-text-primary">AI Backends</span>
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-xxs"
          onClick={() => void backendsQuery.refetch()}
          disabled={backendsQuery.isFetching}
          aria-label="Refresh backends"
        >
          <RefreshCw
            size={11}
            className={backendsQuery.isFetching ? "mr-1 animate-spin" : "mr-1"}
            aria-hidden="true"
          />
          Refresh
        </Button>
      </div>

      {/* Query states */}
      {backendsQuery.isLoading ? (
        <p className="py-6 text-center text-xs text-text-muted">Detecting AI backends…</p>
      ) : backendsQuery.isError ? (
        <p role="alert" className="py-6 text-center text-xs text-loss">
          {backendsQuery.error instanceof Error
            ? backendsQuery.error.message
            : "Could not load AI backends."}
        </p>
      ) : backends.length === 0 ? (
        <p className="py-6 text-center text-xs text-text-muted">
          No AI backends are catalogued on this host.
        </p>
      ) : (
        <>
          {/* LLM providers */}
          {llmBackends.length > 0 && (
            <section aria-label="LLM providers" className="space-y-1.5">
              <h3 className="flex items-center gap-1.5 text-xxs font-semibold uppercase tracking-wider text-text-muted">
                <MessageSquare size={11} aria-hidden="true" /> Chat providers
              </h3>
              {llmBackends.map((backend) => (
                <div
                  key={backend.id}
                  className="rounded-lg border border-border-default bg-surface-base p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium text-text-primary">
                        {backend.display_name}
                      </p>
                      <p className="mt-0.5 text-xxs text-text-muted">{backend.description}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <Badge variant="outline" className="text-xxs">
                        {kindLabel(backend.kind)}
                      </Badge>
                      <Badge variant="outline" className={`text-xxs ${STATUS_META[backend.status].className}`}>
                        {STATUS_META[backend.status].label}
                      </Badge>
                    </div>
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <p className="text-xxs text-text-muted">
                      {backend.status === "ready"
                        ? "Configured — chat with it via the AI Advisor."
                        : "Set the provider and key in Settings to use this backend."}
                    </p>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-6 shrink-0 px-2 text-xxs"
                      onClick={openSettings}
                    >
                      <Settings size={11} className="mr-1" aria-hidden="true" /> Settings
                    </Button>
                  </div>
                </div>
              ))}
            </section>
          )}

          {/* Agent runtimes */}
          {agentBackends.length > 0 && (
            <section aria-label="Agent runtimes" className="space-y-1.5">
              <h3 className="flex items-center gap-1.5 text-xxs font-semibold uppercase tracking-wider text-text-muted">
                <Terminal size={11} aria-hidden="true" /> Agent runtimes
              </h3>
              {agentBackends.map((backend) => {
                const runnable = isRunnable(backend);
                const isActive = activeId === backend.id;
                return (
                  <div
                    key={backend.id}
                    className="rounded-lg border border-border-default bg-surface-base p-3"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium text-text-primary">
                          {backend.display_name}
                        </p>
                        <p className="mt-0.5 text-xxs text-text-muted">{backend.description}</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <Badge variant="outline" className="text-xxs">
                          {kindLabel(backend.kind)}
                        </Badge>
                        <Badge variant="outline" className={`text-xxs ${STATUS_META[backend.status].className}`}>
                          {STATUS_META[backend.status].label}
                        </Badge>
                      </div>
                    </div>

                    <div className="mt-2">
                      {runnable ? (
                        <Button
                          size="sm"
                          variant={isActive ? "outline" : "default"}
                          className="h-6 px-2 text-xxs"
                          onClick={() => toggleRun(backend.id)}
                          aria-expanded={isActive}
                          aria-label={`${isActive ? "Close" : "Run"} ${backend.display_name}`}
                        >
                          <Play size={11} className="mr-1" aria-hidden="true" />
                          {isActive ? "Close runner" : "Run"}
                        </Button>
                      ) : (
                        <p className="text-xxs text-text-muted">
                          Not installed on this host
                          {backend.detect_binaries.length > 0
                            ? ` — install \`${backend.detect_binaries.join("` / `")}\` on PATH to enable it.`
                            : "."}
                        </p>
                      )}
                    </div>

                    {/* Streaming runner */}
                    {runnable && isActive && (
                      <div className="mt-2 space-y-2 border-t border-border-default pt-2">
                        <Textarea
                          value={prompt}
                          onChange={(e) => setPrompt(e.target.value)}
                          placeholder={`Instruction for ${backend.display_name}…`}
                          aria-label={`Prompt for ${backend.display_name}`}
                          className="min-h-[60px] text-xs"
                          disabled={running}
                        />
                        <div className="flex items-center gap-2">
                          <Button
                            size="sm"
                            className="h-7 px-3 text-xs"
                            onClick={() => void start(backend.id)}
                            disabled={running || !prompt.trim()}
                          >
                            {running ? (
                              <Loader2 size={12} className="mr-1 animate-spin" aria-hidden="true" />
                            ) : (
                              <Play size={12} className="mr-1" aria-hidden="true" />
                            )}
                            {running ? "Running…" : "Run agent"}
                          </Button>
                          {running && (
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7 px-3 text-xs"
                              onClick={stop}
                              aria-label="Stop the running agent"
                            >
                              <Square size={12} className="mr-1" aria-hidden="true" /> Stop
                            </Button>
                          )}
                        </div>

                        {runError && (
                          <p role="alert" className="text-xxs text-loss">
                            {runError}
                          </p>
                        )}

                        {(events.length > 0 || running) && (
                          <div
                            className="max-h-48 overflow-y-auto rounded border border-border-default bg-surface-card p-2 text-xs leading-relaxed"
                            data-testid="agent-output"
                          >
                            {events.map((event, i) => (
                              <AgentEventLine key={i} event={event} />
                            ))}
                            {running && (
                              <span className="ml-1 inline-flex items-center gap-1 text-text-muted">
                                <Loader2 size={10} className="animate-spin" aria-hidden="true" /> streaming…
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </section>
          )}
        </>
      )}
    </div>
  );
}
